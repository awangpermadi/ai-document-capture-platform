import logging
from io import BytesIO, IOBase
from unittest.mock import Mock

import pytest
from PIL import Image
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import AnalyzeResult
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import (
    ClientAuthenticationError,
    HttpResponseError,
    ServiceRequestError,
)

from app.services.document_intelligence import (
    AzureDocumentIntelligenceService,
    DocumentIntelligenceError,
)
from app.services.document_input import DocumentValidator


def image_bytes(image_format: str, *, mode: str = "RGB") -> bytes:
    output = BytesIO()
    Image.new(mode, (40, 20), color=128).save(output, format=image_format)
    return output.getvalue()


def service_that_raises(error: Exception) -> AzureDocumentIntelligenceService:
    service = object.__new__(AzureDocumentIntelligenceService)
    service._client = Mock()
    service._client.begin_analyze_document.side_effect = error
    return service


def test_sdk_call_uses_prebuilt_receipt_and_stream_body() -> None:
    content = image_bytes("JPEG")
    document = DocumentValidator.validate(
        content,
        original_filename="receipt.jpg",
        declared_content_type="image/jpeg",
    )
    analyze_result = AnalyzeResult(content="recognized")
    service = object.__new__(AzureDocumentIntelligenceService)
    poller = Mock()
    poller.result.return_value = analyze_result
    service._client = Mock()
    service._client.begin_analyze_document.return_value = poller

    result = service.analyze_document(document)

    assert result is analyze_result
    service._client.begin_analyze_document.assert_called_once()
    call = service._client.begin_analyze_document.call_args.kwargs
    assert call["model_id"] == "prebuilt-receipt"
    assert isinstance(call["body"], IOBase)
    assert call["body"].read() == document.analysis_content
    assert call["content_type"] == "image/jpeg"


def test_azure_sdk_preserves_detected_content_type_for_stream_body() -> None:
    content = image_bytes("PNG")
    document = DocumentValidator.validate(
        content,
        original_filename="receipt.png",
        declared_content_type="image/png",
    )
    client = DocumentIntelligenceClient(
        endpoint="https://example.test",
        credential=AzureKeyCredential("test-key"),
    )
    captured: dict[str, object] = {}

    class RequestCaptured(BaseException):
        pass

    def capture_request(request: object, **_kwargs: object) -> None:
        captured["content_type"] = request.headers.get("Content-Type")  # type: ignore[attr-defined]
        raise RequestCaptured

    client._client._pipeline._transport.send = capture_request
    service = object.__new__(AzureDocumentIntelligenceService)
    service._client = client

    with pytest.raises(RequestCaptured):
        service.analyze_document(document)

    assert captured["content_type"] == "image/png"


@pytest.mark.parametrize(
    ("azure_error", "azure_status", "expected_status", "expected_category"),
    [
        (
            HttpResponseError(message="Invalid document."),
            400,
            422,
            "invalid_document",
        ),
        (
            HttpResponseError(message="Too many requests."),
            429,
            503,
            "throttled",
        ),
        (
            HttpResponseError(message="Azure unavailable."),
            503,
            503,
            "unavailable",
        ),
        (
            ClientAuthenticationError(message="Unauthorized."),
            401,
            502,
            "authentication",
        ),
        (
            ServiceRequestError("Network unavailable."),
            None,
            502,
            "unavailable",
        ),
    ],
)
def test_azure_exceptions_are_classified_and_logged(
    azure_error: Exception,
    azure_status: int | None,
    expected_status: int,
    expected_category: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    if azure_status is not None:
        azure_error.status_code = azure_status  # type: ignore[attr-defined]
    content = image_bytes("JPEG")
    document = DocumentValidator.validate(
        content,
        original_filename="receipt.jpg",
        declared_content_type="image/jpeg",
    )
    service = service_that_raises(azure_error)

    with pytest.raises(DocumentIntelligenceError) as raised:
        service.analyze_document(document)

    error = raised.value
    assert error.status_code == expected_status
    assert error.category == expected_category
    assert error.azure_exception is azure_error
    assert type(azure_error).__name__ in caplog.text
    assert "size_bytes=" in caplog.text
    assert "model_id=prebuilt-receipt" in caplog.text


def test_invalid_input_is_rejected_by_the_validator() -> None:
    with pytest.raises(ValueError):
        DocumentValidator.validate(
            b"not a jpeg",
            original_filename="receipt.jpg",
            declared_content_type="image/jpeg",
        )


def test_service_logs_image_diagnostics(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="app.services.document_input"):
        DocumentValidator.validate(
            image_bytes("JPEG", mode="L"),
            original_filename="receipt.jpg",
            declared_content_type="image/jpeg",
        )

    assert "size_bytes=" in caplog.text
    assert "format=JPEG" in caplog.text
    assert "width=40 height=20 image_mode=L" in caplog.text

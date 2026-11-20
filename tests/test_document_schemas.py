from datetime import date, datetime, time, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.schemas.document import (
    DocumentApprovalRequest,
    DocumentDetail,
    DocumentListItem,
    ReceiptCorrectionRequest,
)


def valid_correction_payload() -> dict[str, object]:
    return {
        "merchant": {
            "name": "Corner Shop",
            "address": "1 Main Street",
            "phone": None,
        },
        "transaction": {
            "date": "2026-11-19",
            "time": "10:30:00",
            "subtotal": 100.0,
            "discount": 5.0,
            "tax": 9.5,
            "tip": None,
            "total": 104.5,
            "cash": 110.0,
            "change": 5.5,
        },
        "items": [
            {
                "id": "existing-item-id",
                "description_raw": "Tea",
                "description_normalized": "Tea",
                "quantity": 2,
                "unit_price": 50.0,
                "total_price": 100.0,
            },
            {
                "id": None,
                "description_raw": "Cake",
                "description_normalized": None,
                "quantity": 1,
                "unit_price": 10.0,
                "total_price": 10.0,
            },
        ],
    }


def test_valid_complete_receipt_correction_defaults_currency() -> None:
    correction = ReceiptCorrectionRequest.model_validate(
        valid_correction_payload()
    )

    assert correction.transaction.currency == "IDR"
    assert correction.transaction.date == date(2026, 11, 19)
    assert correction.items[0].id == "existing-item-id"
    assert correction.items[1].id is None
    assert correction.items[0].confidence is None
    assert correction.items[0].source is None


def test_correction_allows_missing_unit_price_when_total_is_available() -> None:
    payload = valid_correction_payload()
    del payload["items"][0]["unit_price"]  # type: ignore[index]

    correction = ReceiptCorrectionRequest.model_validate(payload)

    assert correction.items[0].quantity == 2
    assert correction.items[0].total_price == 100
    assert correction.items[0].unit_price is None


def test_correction_accepts_server_metadata_but_forbids_unknown_item_fields() -> None:
    payload = valid_correction_payload()
    payload["items"][0]["confidence"] = 0.981  # type: ignore[index]
    payload["items"][0]["source"] = "azure_prebuilt_receipt"  # type: ignore[index]
    correction = ReceiptCorrectionRequest.model_validate(payload)

    assert correction.items[0].confidence == 0.981
    assert correction.items[0].source == "azure_prebuilt_receipt"

    payload["items"][0]["random_field"] = "abc"  # type: ignore[index]
    with pytest.raises(ValidationError) as error:
        ReceiptCorrectionRequest.model_validate(payload)
    assert error.value.errors()[0]["type"] == "extra_forbidden"


@pytest.mark.parametrize(
    ("field_name", "value"),
    [("status", "APPROVED"), ("document_id", "client-controlled-id")],
)
def test_correction_forbids_document_control_fields(
    field_name: str,
    value: str,
) -> None:
    payload = valid_correction_payload()
    payload[field_name] = value

    with pytest.raises(ValidationError) as error:
        ReceiptCorrectionRequest.model_validate(payload)

    assert error.value.errors()[0]["type"] == "extra_forbidden"


def test_correction_rejects_negative_total() -> None:
    payload = valid_correction_payload()
    payload["transaction"]["total"] = -1  # type: ignore[index]

    with pytest.raises(ValidationError):
        ReceiptCorrectionRequest.model_validate(payload)


def test_correction_rejects_zero_quantity() -> None:
    payload = valid_correction_payload()
    payload["items"][0]["quantity"] = 0  # type: ignore[index]

    with pytest.raises(ValidationError):
        ReceiptCorrectionRequest.model_validate(payload)


@pytest.mark.parametrize(
    ("raw", "normalized"),
    [("", None), ("   ", "Tea"), (None, "\t")],
)
def test_correction_rejects_empty_item_descriptions(
    raw: str | None,
    normalized: str | None,
) -> None:
    payload = valid_correction_payload()
    payload["items"][0]["description_raw"] = raw  # type: ignore[index]
    payload["items"][0]["description_normalized"] = normalized  # type: ignore[index]

    with pytest.raises(ValidationError):
        ReceiptCorrectionRequest.model_validate(payload)


def test_approval_rejects_false_confirmation() -> None:
    with pytest.raises(ValidationError):
        DocumentApprovalRequest(
            reviewed_by="Reviewer",
            confirmation=False,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("reviewed_by", ["", " ", "\t\n"])
def test_approval_rejects_empty_reviewer(reviewed_by: str) -> None:
    with pytest.raises(ValidationError):
        DocumentApprovalRequest(
            reviewed_by=reviewed_by,
            confirmation=True,
        )


def test_document_responses_validate_from_orm_attributes() -> None:
    now = datetime.now(timezone.utc)
    orm_receipt = SimpleNamespace(
        document_type="receipt",
        merchant=SimpleNamespace(
            name="Corner Shop",
            address=None,
            phone=None,
        ),
        transaction=SimpleNamespace(
            date=None,
            time=None,
            subtotal=None,
            discount=None,
            tax=None,
            tip=None,
            total=104.5,
            cash=None,
            change=None,
            currency="IDR",
        ),
        items=[],
        extraction_method="prebuilt_receipt",
        confidence=None,
        requires_review=False,
        review_reasons=[],
    )
    document_attributes = {
        "id": "document-1",
        "original_filename": "receipt.pdf",
        "stored_filename": "stored.pdf",
        "content_type": "application/pdf",
        "document_type": "receipt",
        "status": "reviewed",
        "extraction_method": "prebuilt_receipt",
        "requires_review": False,
        "review_reasons": [],
        "error_message": None,
        "receipt": orm_receipt,
        "created_at": now,
        "updated_at": now,
        "reviewed_at": now,
        "approved_at": None,
        "reviewed_by": "Reviewer",
        "raw_ocr_content": "must not appear",
        "azure_endpoint": "must not appear",
    }
    orm_document = SimpleNamespace(**document_attributes)

    list_item = DocumentListItem.model_validate(orm_document)
    detail = DocumentDetail.model_validate(orm_document)

    assert list_item.id == "document-1"
    assert detail.receipt.merchant.name == "Corner Shop"
    assert detail.receipt.transaction.total == 104.5
    assert "raw_ocr_content" not in detail.model_dump()
    assert "azure_endpoint" not in detail.model_dump()

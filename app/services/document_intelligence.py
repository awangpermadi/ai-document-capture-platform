import logging
from collections.abc import Mapping
from io import BytesIO, IOBase

from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import AnalyzeResult
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import (
    AzureError,
    ClientAuthenticationError,
    HttpResponseError,
    ResourceNotFoundError,
    ServiceRequestError,
    ServiceResponseError,
)

from app.config import get_settings
from app.services.document_input import (
    ValidatedDocument,
)

logger = logging.getLogger(__name__)

_PUBLIC_MESSAGES = {
    "authentication": "Document analysis service authentication failed.",
    "throttled": "Document analysis service is temporarily busy.",
    "invalid_document": "Document could not be analyzed.",
    "unavailable": "Document analysis service is unavailable.",
    "unexpected": "Document analysis failed.",
}


class _DocumentBody(IOBase):
    def __init__(self, content: bytes) -> None:
        self._content = content
        self._stream = BytesIO(content)

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)

    def seek(self, offset: int, whence: int = 0) -> int:
        return self._stream.seek(offset, whence)

    def tell(self) -> int:
        return self._stream.tell()

    def __len__(self) -> int:
        return len(self._content)


class DocumentIntelligenceError(RuntimeError):
    """A safe application error retaining Azure diagnostics for server use."""

    def __init__(
        self,
        message: str = "Azure Document Intelligence analysis failed.",
        *,
        category: str = "unexpected",
        status_code: int = 502,
        azure_exception: Exception | None = None,
        azure_error_code: str | None = None,
        azure_error_message: str | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.status_code = status_code
        self.public_message = _PUBLIC_MESSAGES[category]
        self.azure_exception = azure_exception
        self.azure_error_code = azure_error_code
        self.azure_error_message = azure_error_message


class AzureDocumentIntelligenceService:
    MODEL_ID = "prebuilt-receipt"

    def __init__(self) -> None:
        settings = get_settings()
        self._client = DocumentIntelligenceClient(
            endpoint=settings.azure_document_intelligence_endpoint,
            credential=AzureKeyCredential(
                settings.azure_document_intelligence_key
            ),
        )

    def analyze_document(
        self,
        document: ValidatedDocument,
    ) -> AnalyzeResult:
        try:
            poller = self._client.begin_analyze_document(
                model_id=self.MODEL_ID,
                body=_DocumentBody(document.analysis_content),
                content_type=document.detected_content_type,
            )
            return poller.result()
        except ClientAuthenticationError as error:
            raise self._log_azure_error(
                error,
                document,
                category="authentication",
                status_code=502,
            ) from error
        except ResourceNotFoundError as error:
            raise self._log_azure_error(
                error,
                document,
                category="unavailable",
                status_code=502,
            ) from error
        except HttpResponseError as error:
            status_code = getattr(error, "status_code", None)
            error_code = self._error_code(error)
            if status_code == 429 or error_code in {
                "TooManyRequests",
                "Throttled",
            }:
                category = "throttled"
                application_status = 503
            elif status_code in {400, 413, 415} or error_code in {
                "InvalidContent",
                "InvalidDocument",
                "UnsupportedContent",
            }:
                category = "invalid_document"
                application_status = 422
            elif isinstance(status_code, int) and status_code >= 500:
                category = "unavailable"
                application_status = 503
            else:
                category = "unavailable"
                application_status = 502
            raise self._log_azure_error(
                error,
                document,
                category=category,
                status_code=application_status,
            ) from error
        except (ServiceRequestError, ServiceResponseError) as error:
            raise self._log_azure_error(
                error,
                document,
                category="unavailable",
                status_code=502,
            ) from error
        except AzureError as error:
            raise self._log_azure_error(
                error,
                document,
                category="unexpected",
                status_code=502,
            ) from error
        except Exception as error:
            raise self._log_azure_error(
                error,
                document,
                category="unexpected",
                status_code=502,
            ) from error

    @staticmethod
    def _error_code(error: Exception) -> str | None:
        code = getattr(error, "code", None) or getattr(error, "error_code", None)
        azure_error = getattr(error, "error", None)
        if code is None and isinstance(azure_error, Mapping):
            code = azure_error.get("code")
        elif code is None:
            code = getattr(azure_error, "code", None)
        return str(code) if code is not None else None

    @classmethod
    def _log_azure_error(
        cls,
        error: Exception,
        document: ValidatedDocument,
        *,
        category: str,
        status_code: int,
    ) -> DocumentIntelligenceError:
        azure_error_code = cls._error_code(error)
        azure_error_message = getattr(error, "message", None) or str(error)
        settings = get_settings()
        if settings.azure_document_intelligence_key:
            azure_error_message = azure_error_message.replace(
                settings.azure_document_intelligence_key,
                "[REDACTED]",
            )
        azure_http_status = getattr(error, "status_code", None)
        logger.exception(
            "Azure Document Intelligence request failed: "
            "exception_class=%s http_status=%s error_code=%s "
            "error_message=%s content_type=%s size_bytes=%d model_id=%s",
            type(error).__name__,
            azure_http_status,
            azure_error_code,
            azure_error_message,
            document.detected_content_type,
            document.size_bytes,
            cls.MODEL_ID,
        )
        return DocumentIntelligenceError(
            category=category,
            status_code=status_code,
            azure_exception=error,
            azure_error_code=azure_error_code,
            azure_error_message=azure_error_message,
        )

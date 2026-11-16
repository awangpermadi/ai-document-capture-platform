from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import AnalyzeResult
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import AzureError

from app.config import get_settings


class DocumentIntelligenceError(RuntimeError):
    """Raised when Azure Document Intelligence cannot analyze a document."""


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

    def analyze_document(self, document_content: bytes) -> AnalyzeResult:
        try:
            poller = self._client.begin_analyze_document(
                model_id=self.MODEL_ID,
                body=document_content,
            )
            return poller.result()
        except AzureError:
            raise DocumentIntelligenceError(
                "Azure Document Intelligence analysis failed."
            ) from None

import logging
from dataclasses import dataclass

from starlette.concurrency import run_in_threadpool

from app.schemas.receipt import Receipt
from app.services.document_intelligence import (
    AzureDocumentIntelligenceService,
)
from app.services.extraction_validator import ReceiptExtractionValidator
from app.services.receipt_merger import ReceiptMerger
from app.services.receipt_normalizer import ReceiptNormalizer
from app.services.receipt_text_parser import ReceiptTextParser

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReceiptExtractionResult:
    receipt: Receipt
    raw_ocr_content: str | None


class ReceiptExtractionService:
    async def extract(self, content: bytes) -> ReceiptExtractionResult:
        azure_service = AzureDocumentIntelligenceService()
        result = await run_in_threadpool(
            azure_service.analyze_document,
            content,
        )

        azure_receipt = ReceiptNormalizer().normalize(result)
        raw_content = result.content

        if raw_content and raw_content.strip():
            try:
                fallback_receipt = ReceiptTextParser.parse(
                    raw_content,
                    pages=getattr(result, "pages", None),
                )
            except ValueError:
                logger.warning("OCR receipt text fallback parsing failed.")
                fallback_receipt = Receipt()

            final_receipt = ReceiptMerger.merge(
                azure_receipt,
                fallback_receipt,
            )
        else:
            final_receipt = azure_receipt

        final_receipt = ReceiptExtractionValidator.validate(final_receipt)
        return ReceiptExtractionResult(
            receipt=final_receipt,
            raw_ocr_content=raw_content,
        )

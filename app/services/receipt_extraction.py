import logging
from dataclasses import dataclass

from starlette.concurrency import run_in_threadpool

from app.schemas.receipt import Receipt
from app.services.document_input import ValidatedDocument
from app.services.document_intelligence import (
    AzureDocumentIntelligenceService,
)
from app.services.extraction_validator import ReceiptExtractionValidator
from app.services.receipt_merger import ReceiptMerger
from app.services.receipt_normalizer import ReceiptNormalizer
from app.services.receipt_reconciler import ReceiptReconciler
from app.services.receipt_text_parser import ReceiptTextParser

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReceiptExtractionResult:
    receipt: Receipt
    raw_ocr_content: str | None


class ReceiptExtractionService:
    async def extract(
        self,
        document: ValidatedDocument,
    ) -> ReceiptExtractionResult:
        azure_service = AzureDocumentIntelligenceService()
        result = await run_in_threadpool(
            azure_service.analyze_document,
            document,
        )

        azure_receipt = ReceiptNormalizer().normalize(result)
        structured_total = azure_receipt.transaction.total
        structured_change = azure_receipt.transaction.change
        raw_content = result.content
        fallback_receipt = Receipt()

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

        reconciliation_reasons = ReceiptReconciler.reconcile(
            final_receipt,
            structured_total=structured_total,
            structured_change=structured_change,
            ocr_receipt=fallback_receipt,
        )
        final_receipt = ReceiptExtractionValidator.validate(final_receipt)
        if reconciliation_reasons:
            final_receipt.requires_review = True
            final_receipt.review_reasons.extend(
                reason
                for reason in reconciliation_reasons
                if reason not in final_receipt.review_reasons
            )
        return ReceiptExtractionResult(
            receipt=final_receipt,
            raw_ocr_content=raw_content,
        )

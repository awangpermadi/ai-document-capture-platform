import json
import logging
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import DocumentReviewPersistenceError
from app.models import Document, DocumentStatus, ReceiptItemModel, ReceiptModel
from app.schemas.receipt import Receipt

logger = logging.getLogger(__name__)


class ReceiptPersistenceService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def persist(
        self,
        *,
        original_filename: str,
        stored_filename: str,
        content_type: str,
        receipt: Receipt,
        raw_ocr_content: str | None,
    ) -> Document:
        try:
            document = Document(
                id=str(uuid4()),
                original_filename=original_filename,
                stored_filename=stored_filename,
                content_type=content_type,
                document_type="receipt",
                status=(
                    DocumentStatus.REVIEW_REQUIRED
                    if receipt.requires_review
                    else DocumentStatus.EXTRACTED
                ),
                extraction_method=receipt.extraction_method,
                requires_review=receipt.requires_review,
                review_reasons=json.dumps(receipt.review_reasons),
                raw_ocr_content=raw_ocr_content,
            )
            persisted_receipt = ReceiptModel(
                id=str(uuid4()),
                merchant_name=receipt.merchant.name,
                merchant_address=receipt.merchant.address,
                merchant_phone=receipt.merchant.phone,
                transaction_date=receipt.transaction.date,
                transaction_time=receipt.transaction.time,
                subtotal=receipt.transaction.subtotal,
                discount=receipt.transaction.discount,
                tax=receipt.transaction.tax,
                tip=receipt.transaction.tip,
                total=receipt.transaction.total,
                cash=receipt.transaction.cash,
                change=receipt.transaction.change,
                currency=receipt.transaction.currency,
                payment_method=receipt.transaction.payment_method,
                extraction_method=receipt.extraction_method,
                confidence=receipt.confidence,
            )
            persisted_receipt.items = [
                ReceiptItemModel(
                    id=str(uuid4()),
                    line_number=line_number,
                    description_raw=item.description_raw,
                    description_normalized=item.description_normalized,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    total_price=item.total_price,
                    confidence=item.confidence,
                    source=item.source,
                )
                for line_number, item in enumerate(receipt.items, start=1)
            ]
            document.receipt = persisted_receipt

            self._session.add(document)
            await self._session.commit()
            return document
        except Exception as error:
            await self._session.rollback()
            logger.exception("Receipt persistence failed")
            if isinstance(error, SQLAlchemyError):
                raise DocumentReviewPersistenceError() from None
            raise

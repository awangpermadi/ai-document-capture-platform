import json
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.exceptions import (
    DocumentApprovalValidationError,
    DocumentNotFoundError,
    DocumentReviewPersistenceError,
    DocumentStateConflictError,
)
from app.models import Document, DocumentStatus, ReceiptItemModel, ReceiptModel
from app.schemas.document import (
    DocumentActionResponse,
    DocumentDetail,
    DocumentListItem,
    ReceiptCorrectionRequest,
)


class DocumentReviewService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_documents(
        self,
        status: DocumentStatus | None = None,
        requires_review: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[DocumentListItem]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100.")
        if offset < 0:
            raise ValueError("offset must be non-negative.")

        statement = select(Document).order_by(Document.created_at.desc())
        if status is not None:
            statement = statement.where(Document.status == status)
        if requires_review is not None:
            statement = statement.where(Document.requires_review.is_(requires_review))

        try:
            result = await self._session.execute(statement.limit(limit).offset(offset))
            return [
                DocumentListItem.model_validate(document)
                for document in result.scalars().all()
            ]
        except SQLAlchemyError:
            raise DocumentReviewPersistenceError() from None

    async def get_document_detail(self, document_id: str) -> DocumentDetail:
        try:
            document = await self._load_document(document_id)
            return self._to_document_detail(document)
        except DocumentNotFoundError:
            raise
        except SQLAlchemyError:
            raise DocumentReviewPersistenceError() from None

    async def update_receipt_correction(
        self,
        document_id: str,
        correction: ReceiptCorrectionRequest,
        reviewed_by: str,
    ) -> DocumentDetail:
        try:
            document = await self._load_document(document_id)
            if document.status == DocumentStatus.APPROVED:
                raise DocumentStateConflictError(
                    "Approved documents cannot be corrected."
                )
            if document.status == DocumentStatus.FAILED:
                raise DocumentStateConflictError(
                    "Failed documents cannot be corrected."
                )
            if not reviewed_by.strip():
                raise DocumentStateConflictError("A reviewer is required.")

            receipt = document.receipt
            if receipt is None:
                receipt = ReceiptModel(id=str(uuid4()), document_id=document.id)
                document.receipt = receipt

            receipt.merchant_name = correction.merchant.name
            receipt.merchant_address = correction.merchant.address
            receipt.merchant_phone = correction.merchant.phone
            receipt.transaction_date = correction.transaction.date
            receipt.transaction_time = correction.transaction.time
            receipt.subtotal = correction.transaction.subtotal
            receipt.discount = correction.transaction.discount
            receipt.tax = correction.transaction.tax
            receipt.tip = correction.transaction.tip
            receipt.total = correction.transaction.total
            receipt.cash = correction.transaction.cash
            receipt.change = correction.transaction.change
            receipt.currency = correction.transaction.currency

            old_items = {item.id: item for item in receipt.items}
            used_item_ids: set[str] = set()
            replacement_items: list[ReceiptItemModel] = []
            for line_number, corrected_item in enumerate(correction.items, start=1):
                if corrected_item.id is None:
                    item = ReceiptItemModel(
                        id=str(uuid4()),
                        receipt_id=receipt.id,
                    )
                    item_changed = True
                else:
                    if corrected_item.id in used_item_ids:
                        raise DocumentStateConflictError(
                            "A receipt item ID was supplied more than once."
                        )
                    item = old_items.get(corrected_item.id)
                    if item is None:
                        raise DocumentStateConflictError(
                            "Receipt item does not belong to this receipt."
                        )
                    used_item_ids.add(corrected_item.id)
                    item_changed = any(
                        getattr(item, field_name)
                        != getattr(corrected_item, field_name)
                        for field_name in (
                            "description_raw",
                            "description_normalized",
                            "quantity",
                            "unit_price",
                            "total_price",
                        )
                    )

                item.line_number = line_number
                item.description_raw = corrected_item.description_raw
                item.description_normalized = (
                    corrected_item.description_normalized
                )
                item.quantity = corrected_item.quantity
                item.unit_price = corrected_item.unit_price
                item.total_price = corrected_item.total_price
                if item_changed:
                    item.confidence = None
                    item.source = "human_review"
                replacement_items.append(item)

            receipt.items = replacement_items
            document.status = DocumentStatus.REVIEW_REQUIRED
            document.requires_review = True
            document.reviewed_by = reviewed_by
            document.reviewed_at = self._utc_now()
            document.updated_at = self._utc_now()

            await self._session.commit()
            return self._to_document_detail(document)
        except (DocumentNotFoundError, DocumentStateConflictError):
            await self._session.rollback()
            raise
        except Exception as error:
            await self._session.rollback()
            if isinstance(error, SQLAlchemyError):
                raise DocumentReviewPersistenceError() from None
            raise

    async def approve_document(
        self,
        document_id: str,
        reviewed_by: str,
    ) -> DocumentActionResponse:
        try:
            document = await self._load_document(document_id)
            if document.status == DocumentStatus.FAILED:
                raise DocumentStateConflictError(
                    "Failed documents cannot be approved."
                )
            if document.status == DocumentStatus.APPROVED:
                response = self._action_response(
                    document,
                    "Document is already approved.",
                )
                await self._session.rollback()
                return response

            errors = self._approval_errors(document, reviewed_by)
            if errors:
                raise DocumentApprovalValidationError(errors)

            document.status = DocumentStatus.APPROVED
            document.requires_review = False
            document.review_reasons = "[]"
            document.reviewed_by = reviewed_by
            if document.reviewed_at is None:
                document.reviewed_at = self._utc_now()
            document.approved_at = self._utc_now()
            document.updated_at = self._utc_now()

            await self._session.commit()
            return self._action_response(document, "Document approved.")
        except (DocumentNotFoundError, DocumentStateConflictError):
            await self._session.rollback()
            raise
        except DocumentApprovalValidationError:
            await self._session.rollback()
            raise
        except Exception as error:
            await self._session.rollback()
            if isinstance(error, SQLAlchemyError):
                raise DocumentReviewPersistenceError() from None
            raise

    async def _load_document(self, document_id: str) -> Document:
        statement = (
            select(Document)
            .options(
                selectinload(Document.receipt).selectinload(ReceiptModel.items)
            )
            .where(Document.id == document_id)
        )
        result = await self._session.execute(statement)
        document = result.scalar_one_or_none()
        if document is None:
            raise DocumentNotFoundError()
        return document

    @staticmethod
    def _to_document_detail(document: Document) -> DocumentDetail:
        review_reasons = DocumentReviewService._parse_review_reasons(
            document.review_reasons
        )
        receipt: dict[str, object] = {}
        if document.receipt is not None:
            model = document.receipt
            receipt = {
                "document_type": document.document_type,
                "merchant": {
                    "name": model.merchant_name,
                    "address": model.merchant_address,
                    "phone": model.merchant_phone,
                },
                "transaction": {
                    "date": model.transaction_date,
                    "time": model.transaction_time,
                    "subtotal": model.subtotal,
                    "discount": model.discount,
                    "tax": model.tax,
                    "tip": model.tip,
                    "total": model.total,
                    "cash": model.cash,
                    "change": model.change,
                    "currency": model.currency,
                },
                "items": [
                    {
                        "id": item.id,
                        "description_raw": item.description_raw,
                        "description_normalized": item.description_normalized,
                        "quantity": item.quantity,
                        "unit_price": item.unit_price,
                        "total_price": item.total_price,
                        "confidence": item.confidence,
                        "source": item.source,
                    }
                    for item in sorted(
                        model.items,
                        key=lambda receipt_item: receipt_item.line_number,
                    )
                ],
                "extraction_method": model.extraction_method,
                "confidence": model.confidence,
                "requires_review": document.requires_review,
                "review_reasons": review_reasons,
            }

        return DocumentDetail.model_validate(
            {
                "id": document.id,
                "original_filename": document.original_filename,
                "stored_filename": document.stored_filename,
                "content_type": document.content_type,
                "document_type": document.document_type,
                "status": document.status,
                "extraction_method": document.extraction_method,
                "requires_review": document.requires_review,
                "review_reasons": review_reasons,
                "error_message": document.error_message,
                "receipt": receipt,
                "created_at": DocumentReviewService._as_utc(document.created_at),
                "updated_at": DocumentReviewService._as_utc(document.updated_at),
                "reviewed_at": DocumentReviewService._as_utc(
                    document.reviewed_at
                ),
                "approved_at": DocumentReviewService._as_utc(
                    document.approved_at
                ),
                "reviewed_by": document.reviewed_by,
            }
        )

    @staticmethod
    def _parse_review_reasons(value: str | list[str]) -> list[str]:
        if isinstance(value, list):
            reasons = value
        else:
            try:
                reasons = json.loads(value)
            except (TypeError, json.JSONDecodeError):
                raise DocumentReviewPersistenceError() from None
        if not isinstance(reasons, list) or not all(
            isinstance(reason, str) for reason in reasons
        ):
            raise DocumentReviewPersistenceError()
        return reasons

    @staticmethod
    def _approval_errors(document: Document, reviewed_by: str) -> list[str]:
        errors: list[str] = []
        if not reviewed_by.strip():
            errors.append("A reviewer is required.")

        receipt = document.receipt
        if receipt is None:
            errors.append("A receipt is required.")
            return errors

        if not receipt.merchant_name or not receipt.merchant_name.strip():
            errors.append("Merchant name is required.")
        if receipt.total is None or not receipt.total >= 0:
            errors.append("A non-negative total is required.")
        if not receipt.items:
            errors.append("At least one receipt item is required.")

        for line_number, item in enumerate(receipt.items, start=1):
            descriptions = (
                item.description_raw,
                item.description_normalized,
            )
            if not any(
                description is not None and description.strip()
                for description in descriptions
            ):
                errors.append(
                    f"Receipt item {line_number} requires a description."
                )
            if item.quantity is not None and not item.quantity > 0:
                errors.append(
                    f"Receipt item {line_number} quantity must be greater than zero."
                )

        if (
            receipt.cash is not None
            and receipt.total is not None
            and receipt.change is not None
            and not abs((receipt.cash - receipt.total) - receipt.change) <= 1
        ):
            errors.append("Cash, total, and change are inconsistent.")

        if (
            receipt.subtotal is not None
            and receipt.discount is not None
            and receipt.subtotal - receipt.discount < 0
        ):
            errors.append("Discount cannot exceed subtotal.")

        return errors

    @staticmethod
    def _action_response(
        document: Document,
        message: str,
    ) -> DocumentActionResponse:
        return DocumentActionResponse(
            document_id=document.id,
            status=document.status.value,
            message=message,
            updated_at=DocumentReviewService._as_utc(document.updated_at),
            reviewed_at=DocumentReviewService._as_utc(document.reviewed_at),
            approved_at=DocumentReviewService._as_utc(document.approved_at),
        )

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _as_utc(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

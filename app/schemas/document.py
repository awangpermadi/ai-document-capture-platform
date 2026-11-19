from datetime import date as Date, datetime, time as Time
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.receipt import ReceiptRead


NonNegativeAmount = Annotated[float | None, Field(ge=0)]
PositiveQuantity = Annotated[float | None, Field(gt=0)]


class DocumentListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    original_filename: str
    content_type: str
    document_type: str
    status: str
    extraction_method: str | None = None
    requires_review: bool
    created_at: datetime
    updated_at: datetime
    reviewed_at: datetime | None = None
    approved_at: datetime | None = None


class DocumentDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    original_filename: str
    stored_filename: str | None
    content_type: str
    document_type: str
    status: str
    extraction_method: str | None = None
    requires_review: bool
    review_reasons: list[str]
    error_message: str | None = None
    receipt: ReceiptRead
    created_at: datetime
    updated_at: datetime
    reviewed_at: datetime | None = None
    approved_at: datetime | None = None
    reviewed_by: str | None = None


class ReceiptCorrectionMerchant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None
    address: str | None
    phone: str | None


class ReceiptCorrectionTransaction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: Date | None
    time: Time | None
    subtotal: NonNegativeAmount
    discount: NonNegativeAmount
    tax: NonNegativeAmount
    tip: NonNegativeAmount
    total: NonNegativeAmount
    cash: NonNegativeAmount
    change: NonNegativeAmount
    currency: str = "IDR"


class ReceiptItemCorrection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    description_raw: str | None
    description_normalized: str | None
    quantity: PositiveQuantity
    unit_price: NonNegativeAmount
    total_price: NonNegativeAmount
    confidence: float | None = Field(
        default=None,
        description="Round-trip compatibility only; the server ignores this value.",
    )
    source: str | None = Field(
        default=None,
        description="Round-trip compatibility only; the server ignores this value.",
    )

    @model_validator(mode="after")
    def require_nonempty_description(self) -> "ReceiptItemCorrection":
        descriptions = (
            self.description_raw,
            self.description_normalized,
        )
        if not any(
            description is not None and description.strip()
            for description in descriptions
        ):
            raise ValueError("An item must have a non-empty description.")
        if any(
            description is not None and not description.strip()
            for description in descriptions
        ):
            raise ValueError("Item descriptions cannot be empty.")
        return self


class ReceiptCorrectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    merchant: ReceiptCorrectionMerchant
    transaction: ReceiptCorrectionTransaction
    items: list[ReceiptItemCorrection]

    @model_validator(mode="before")
    @classmethod
    def ignore_receipt_read_metadata(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        read_only_fields = {
            "document_type",
            "extraction_method",
            "confidence",
            "requires_review",
            "review_reasons",
        }
        return {
            field_name: field_value
            for field_name, field_value in value.items()
            if field_name not in read_only_fields
        }


class DocumentApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviewed_by: str
    confirmation: Literal[True]

    @model_validator(mode="after")
    def require_nonempty_reviewer(self) -> "DocumentApprovalRequest":
        if not self.reviewed_by.strip():
            raise ValueError("reviewed_by cannot be empty.")
        return self


class DocumentActionResponse(BaseModel):
    document_id: str
    status: str
    message: str
    updated_at: datetime
    reviewed_at: datetime | None = None
    approved_at: datetime | None = None


class DocumentProcessResponse(BaseModel):
    document_id: str
    status: str
    receipt: ReceiptRead
    requires_review: bool
    review_reasons: list[str]
    created_at: datetime

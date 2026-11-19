from datetime import date as Date, time as Time

from pydantic import BaseModel, ConfigDict, Field


class Merchant(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str | None = None
    address: str | None = None
    phone: str | None = None


class ReceiptItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    description_raw: str | None = None
    description_normalized: str | None = None
    quantity: float | None = None
    unit_price: float | None = None
    total_price: float | None = None
    confidence: float | None = None
    source: str = "azure_prebuilt_receipt"


class ReceiptItemRead(ReceiptItem):
    id: str | None = None


class Transaction(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    date: Date | None = None
    time: Time | None = None
    subtotal: float | None = None
    discount: float | None = None
    tax: float | None = None
    tip: float | None = None
    total: float | None = None
    cash: float | None = None
    change: float | None = None
    currency: str | None = None


class Receipt(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_type: str = "receipt"

    merchant: Merchant = Field(default_factory=Merchant)
    transaction: Transaction = Field(default_factory=Transaction)
    items: list[ReceiptItem] = Field(default_factory=list)

    extraction_method: str = "prebuilt_receipt"
    confidence: float | None = None

    requires_review: bool = False
    review_reasons: list[str] = Field(default_factory=list)


class ReceiptRead(Receipt):
    items: list[ReceiptItemRead] = Field(default_factory=list)
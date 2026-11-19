from datetime import date, time
from typing import TYPE_CHECKING

from sqlalchemy import Date, Float, ForeignKey, Integer, String, Time
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.document import Document


class ReceiptModel(Base):
    __tablename__ = "receipts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    merchant_name: Mapped[str | None] = mapped_column(String(255))
    merchant_address: Mapped[str | None] = mapped_column(String(1000))
    merchant_phone: Mapped[str | None] = mapped_column(String(100))
    transaction_date: Mapped[date | None] = mapped_column(Date)
    transaction_time: Mapped[time | None] = mapped_column(Time)
    # TODO: use Numeric(18, 2) for monetary columns before production.
    subtotal: Mapped[float | None] = mapped_column(Float)
    discount: Mapped[float | None] = mapped_column(Float)
    tax: Mapped[float | None] = mapped_column(Float)
    tip: Mapped[float | None] = mapped_column(Float)
    total: Mapped[float | None] = mapped_column(Float)
    cash: Mapped[float | None] = mapped_column(Float)
    change: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str | None] = mapped_column(String(10), default="IDR")
    extraction_method: Mapped[str] = mapped_column(
        String(100), default="prebuilt_receipt"
    )
    confidence: Mapped[float | None] = mapped_column(Float)

    document: Mapped["Document"] = relationship(
        "Document", back_populates="receipt"
    )
    items: Mapped[list["ReceiptItemModel"]] = relationship(
        "ReceiptItemModel",
        back_populates="receipt",
        cascade="all, delete-orphan",
        order_by="ReceiptItemModel.line_number",
        lazy="selectin",
    )


class ReceiptItemModel(Base):
    __tablename__ = "receipt_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    receipt_id: Mapped[str] = mapped_column(
        ForeignKey("receipts.id", ondelete="CASCADE"), index=True
    )
    line_number: Mapped[int] = mapped_column(Integer)
    description_raw: Mapped[str | None] = mapped_column(String(1000))
    description_normalized: Mapped[str | None] = mapped_column(String(1000))
    quantity: Mapped[float | None] = mapped_column(Float)
    unit_price: Mapped[float | None] = mapped_column(Float)
    total_price: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(100), default="azure_prebuilt_receipt")

    receipt: Mapped[ReceiptModel] = relationship(
        "ReceiptModel", back_populates="items"
    )

from collections.abc import AsyncIterator
from datetime import date, time
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import selectinload

from app.database.init_db import initialize_database
from app.models import (
    Document,
    DocumentStatus,
    ReceiptItemModel,
    ReceiptModel,
)
from app.schemas.receipt import Merchant, Receipt, ReceiptItem, Transaction
from app.services.receipt_persistence import ReceiptPersistenceService


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def persistence_session(
    tmp_path: Path,
    anyio_backend: str,
) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'receipt-persistence.db'}"
    )
    await initialize_database(engine)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        yield session

    await engine.dispose()


def tlogomas_receipt(*, requires_review: bool = False) -> Receipt:
    return Receipt(
        merchant=Merchant(name="TLOGOMAS 44 MALANG"),
        transaction=Transaction(
            date=date(2022, 1, 21),
            time=time(18, 27),
            subtotal=77400,
            discount=2000,
            tax=7036,
            tip=None,
            total=75400,
            cash=100500,
            change=25100,
            currency="IDR",
        ),
        items=[
            ReceiptItem(
                description_raw="Receipt item one",
                description_normalized="Receipt item one",
                quantity=1,
                unit_price=50000,
                total_price=50000,
                confidence=0.98,
            ),
            ReceiptItem(
                description_raw="Receipt item two",
                description_normalized="Receipt item two",
                quantity=1,
                unit_price=27400,
                total_price=27400,
                confidence=0.97,
            ),
        ],
        extraction_method="prebuilt_receipt_with_ocr_fallback",
        confidence=0.99,
        requires_review=requires_review,
        review_reasons=["Test review reason"] if requires_review else [],
    )


@pytest.mark.anyio
async def test_persists_tlogomas_receipt_and_related_items(
    persistence_session: AsyncSession,
) -> None:
    document = await ReceiptPersistenceService(persistence_session).persist(
        original_filename="tlogomas.pdf",
        stored_filename="uuid-receipt.pdf",
        content_type="application/pdf",
        receipt=tlogomas_receipt(),
        raw_ocr_content="TUNAI\n100,500",
    )

    persisted_document = (
        await persistence_session.execute(
            select(Document)
            .where(Document.id == document.id)
            .options(
                selectinload(Document.receipt).selectinload(
                    ReceiptModel.items
                )
            )
        )
    ).scalar_one()
    receipt = persisted_document.receipt

    assert receipt is not None
    assert persisted_document.status is DocumentStatus.EXTRACTED
    assert persisted_document.requires_review is False
    assert persisted_document.raw_ocr_content == "TUNAI\n100,500"
    assert receipt.merchant_name == "TLOGOMAS 44 MALANG"
    assert receipt.transaction_date == date(2022, 1, 21)
    assert receipt.transaction_time == time(18, 27)
    assert receipt.subtotal == 77400
    assert receipt.discount == 2000
    assert receipt.tax == 7036
    assert receipt.tip is None
    assert receipt.total == 75400
    assert receipt.cash == 100500
    assert receipt.change == 25100
    assert receipt.currency == "IDR"
    assert receipt.confidence == 0.99
    assert [item.line_number for item in receipt.items] == [1, 2]
    assert all(item.source == "azure_prebuilt_receipt" for item in receipt.items)
    assert await persistence_session.scalar(
        select(func.count()).select_from(ReceiptModel)
    ) == 1
    assert await persistence_session.scalar(
        select(func.count()).select_from(ReceiptItemModel)
    ) == 2


@pytest.mark.anyio
async def test_persistence_maps_review_flag_to_document_status(
    persistence_session: AsyncSession,
) -> None:
    document = await ReceiptPersistenceService(persistence_session).persist(
        original_filename="needs-review.pdf",
        stored_filename="uuid-review.pdf",
        content_type="application/pdf",
        receipt=tlogomas_receipt(requires_review=True),
        raw_ocr_content=None,
    )

    assert document.status is DocumentStatus.REVIEW_REQUIRED
    assert document.requires_review is True
    assert document.review_reasons == '["Test review reason"]'

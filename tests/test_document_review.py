import json
from collections.abc import AsyncIterator
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.exceptions import (
    DocumentApprovalValidationError,
    DocumentNotFoundError,
    DocumentReviewPersistenceError,
    DocumentStateConflictError,
)
from app.models import Base, Document, DocumentStatus, ReceiptItemModel, ReceiptModel
from app.schemas.document import ReceiptCorrectionRequest
from app.services.document_review import DocumentReviewService


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def db_session(
    tmp_path: Path,
    anyio_backend: str,
) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'document-review.db'}"
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


def correction_payload(
    *,
    item_id: str | None = None,
    items: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    if items is None:
        items = [
            {
                "id": item_id,
                "description_raw": "Reviewed item",
                "description_normalized": "Reviewed item",
                "quantity": 1,
                "unit_price": 75400,
                "total_price": 75400,
            }
        ]
    return {
        "merchant": {
            "name": "Reviewed merchant",
            "address": "1 Review Street",
            "phone": "555-0100",
        },
        "transaction": {
            "date": "2022-01-21",
            "time": "18:27:00",
            "subtotal": 77400,
            "discount": 2000,
            "tax": 7036,
            "tip": None,
            "total": 75400,
            "cash": 100500,
            "change": 25100,
            "currency": "IDR",
        },
        "items": items,
    }


async def create_document(
    session: AsyncSession,
    *,
    status: DocumentStatus = DocumentStatus.REVIEW_REQUIRED,
    requires_review: bool = True,
    with_receipt: bool = True,
    items: list[tuple[str, str, int]] | None = None,
    created_at: datetime | None = None,
    total: float | None = 75400,
    cash: float | None = 100500,
    change: float | None = 25100,
) -> tuple[Document, list[ReceiptItemModel]]:
    document = Document(
        id=str(uuid4()),
        original_filename="receipt.pdf",
        stored_filename="stored-receipt.pdf",
        content_type="application/pdf",
        document_type="receipt",
        status=status,
        extraction_method="prebuilt_receipt",
        requires_review=requires_review,
        review_reasons=json.dumps(["Check receipt"]),
        created_at=created_at or datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    receipt_items: list[ReceiptItemModel] = []
    if with_receipt:
        receipt = ReceiptModel(
            id=str(uuid4()),
            merchant_name="Original merchant",
            merchant_address="Old address",
            merchant_phone="555-0000",
            transaction_date=date(2022, 1, 21),
            transaction_time=time(18, 27),
            subtotal=77400,
            discount=2000,
            tax=7036,
            total=total,
            cash=cash,
            change=change,
            currency="IDR",
            extraction_method="prebuilt_receipt",
        )
        item_data = items if items is not None else [("Existing item", "Existing item", 1)]
        for line_number, (description, normalized, quantity) in enumerate(
            item_data,
            start=1,
        ):
            receipt_items.append(
                ReceiptItemModel(
                    id=str(uuid4()),
                    line_number=line_number,
                    description_raw=description,
                    description_normalized=normalized,
                    quantity=quantity,
                    unit_price=75400,
                    total_price=75400,
                    confidence=0.9,
                    source="azure_prebuilt_receipt",
                )
            )
        receipt.items = receipt_items
        document.receipt = receipt

    session.add(document)
    await session.commit()
    return document, receipt_items


@pytest.mark.anyio
async def test_list_documents_orders_all_documents_by_creation_time(
    db_session: AsyncSession,
) -> None:
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    oldest, _ = await create_document(db_session, created_at=base_time)
    newest, _ = await create_document(
        db_session,
        created_at=base_time + timedelta(days=2),
    )
    middle, _ = await create_document(
        db_session,
        created_at=base_time + timedelta(days=1),
    )

    documents = await DocumentReviewService(db_session).list_documents()

    assert [document.id for document in documents] == [
        newest.id,
        middle.id,
        oldest.id,
    ]
    assert all(not hasattr(document, "raw_ocr_content") for document in documents)


@pytest.mark.anyio
async def test_list_documents_filters_review_required(
    db_session: AsyncSession,
) -> None:
    review_required, _ = await create_document(db_session)
    await create_document(
        db_session,
        status=DocumentStatus.APPROVED,
        requires_review=False,
    )

    documents = await DocumentReviewService(db_session).list_documents(
        status=DocumentStatus.REVIEW_REQUIRED,
        requires_review=True,
    )

    assert [document.id for document in documents] == [review_required.id]


@pytest.mark.anyio
async def test_get_document_detail_parses_reasons_and_orders_items(
    db_session: AsyncSession,
) -> None:
    document, _ = await create_document(
        db_session,
        items=[("First", "First", 1), ("Second", "Second", 2)],
    )

    detail = await DocumentReviewService(db_session).get_document_detail(
        document.id
    )

    assert detail.review_reasons == ["Check receipt"]
    assert [
        item.description_normalized for item in detail.receipt.items
    ] == ["First", "Second"]


@pytest.mark.anyio
async def test_get_document_detail_raises_when_missing(
    db_session: AsyncSession,
) -> None:
    with pytest.raises(DocumentNotFoundError):
        await DocumentReviewService(db_session).get_document_detail("missing")


@pytest.mark.anyio
async def test_correction_updates_merchant_and_transaction(
    db_session: AsyncSession,
) -> None:
    document, _ = await create_document(db_session)
    correction = ReceiptCorrectionRequest.model_validate(correction_payload())

    detail = await DocumentReviewService(db_session).update_receipt_correction(
        document.id,
        correction,
        "Reviewer",
    )

    assert detail.receipt.merchant.name == "Reviewed merchant"
    assert detail.receipt.merchant.address == "1 Review Street"
    assert detail.receipt.transaction.date == date(2022, 1, 21)
    assert detail.receipt.transaction.time == time(18, 27)
    assert detail.receipt.transaction.subtotal == 77400
    assert detail.receipt.transaction.tax == 7036
    assert detail.receipt.transaction.total == 75400
    assert detail.status == DocumentStatus.REVIEW_REQUIRED.value
    assert detail.reviewed_by == "Reviewer"


@pytest.mark.anyio
async def test_correction_updates_discount_cash_and_change(
    db_session: AsyncSession,
) -> None:
    document, _ = await create_document(db_session)
    payload = correction_payload()
    payload["transaction"]["discount"] = 2000  # type: ignore[index]
    payload["transaction"]["cash"] = 100500  # type: ignore[index]
    payload["transaction"]["change"] = 25100  # type: ignore[index]
    correction = ReceiptCorrectionRequest.model_validate(payload)

    detail = await DocumentReviewService(db_session).update_receipt_correction(
        document.id,
        correction,
        "Reviewer",
    )

    assert detail.receipt.transaction.discount == 2000
    assert detail.receipt.transaction.cash == 100500
    assert detail.receipt.transaction.change == 25100


@pytest.mark.anyio
async def test_correction_replaces_items_and_preserves_owned_id(
    db_session: AsyncSession,
) -> None:
    document, old_items = await create_document(
        db_session,
        items=[("Old one", "Old one", 1), ("Old two", "Old two", 1)],
    )
    keep_id = old_items[1].id
    payload = correction_payload(
        items=[
            {
                "id": keep_id,
                "description_raw": "Updated existing",
                "description_normalized": "Updated existing",
                "quantity": 2,
                "unit_price": 20,
                "total_price": 40,
            },
            {
                "id": None,
                "description_raw": "New item",
                "description_normalized": "New item",
                "quantity": 1,
                "unit_price": 10,
                "total_price": 10,
            },
        ]
    )
    correction = ReceiptCorrectionRequest.model_validate(payload)

    detail = await DocumentReviewService(db_session).update_receipt_correction(
        document.id,
        correction,
        "Reviewer",
    )

    stored_items = list(
        (
            await db_session.execute(
                select(ReceiptItemModel)
                .where(ReceiptItemModel.receipt_id == document.receipt.id)
                .order_by(ReceiptItemModel.line_number)
            )
        ).scalars()
    )
    assert len(stored_items) == 2
    assert stored_items[0].id == keep_id
    assert [item.line_number for item in stored_items] == [1, 2]
    assert all(item.source == "human_review" for item in stored_items)
    assert all(item.confidence is None for item in stored_items)
    assert [item.description_normalized for item in detail.receipt.items] == [
        "Updated existing",
        "New item",
    ]


@pytest.mark.anyio
async def test_correction_rejects_item_id_from_another_receipt(
    db_session: AsyncSession,
) -> None:
    document, _ = await create_document(db_session)
    document_id = document.id
    _, foreign_items = await create_document(db_session)
    correction = ReceiptCorrectionRequest.model_validate(
        correction_payload(item_id=foreign_items[0].id)
    )

    with pytest.raises(DocumentStateConflictError):
        await DocumentReviewService(db_session).update_receipt_correction(
            document_id,
            correction,
            "Reviewer",
        )

    detail = await DocumentReviewService(db_session).get_document_detail(
        document_id
    )
    assert detail.receipt.merchant.name == "Original merchant"


@pytest.mark.anyio
async def test_correction_rejects_approved_document(
    db_session: AsyncSession,
) -> None:
    document, _ = await create_document(db_session, status=DocumentStatus.APPROVED)
    correction = ReceiptCorrectionRequest.model_validate(correction_payload())

    with pytest.raises(DocumentStateConflictError):
        await DocumentReviewService(db_session).update_receipt_correction(
            document.id,
            correction,
            "Reviewer",
        )


@pytest.mark.anyio
async def test_correction_rejects_failed_document(
    db_session: AsyncSession,
) -> None:
    document, _ = await create_document(db_session, status=DocumentStatus.FAILED)
    correction = ReceiptCorrectionRequest.model_validate(correction_payload())

    with pytest.raises(DocumentStateConflictError):
        await DocumentReviewService(db_session).update_receipt_correction(
            document.id,
            correction,
            "Reviewer",
        )


@pytest.mark.anyio
async def test_approve_valid_document(
    db_session: AsyncSession,
) -> None:
    document, _ = await create_document(db_session)

    response = await DocumentReviewService(db_session).approve_document(
        document.id,
        "Reviewer",
    )

    assert response.document_id == document.id
    assert response.status == DocumentStatus.APPROVED.value
    assert response.reviewed_at is not None
    assert response.approved_at is not None
    persisted = await db_session.get(Document, document.id)
    assert persisted is not None
    assert persisted.requires_review is False
    assert persisted.review_reasons == "[]"


@pytest.mark.anyio
async def test_approval_rejects_failed_document(
    db_session: AsyncSession,
) -> None:
    document, _ = await create_document(db_session, status=DocumentStatus.FAILED)

    with pytest.raises(DocumentStateConflictError):
        await DocumentReviewService(db_session).approve_document(
            document.id,
            "Reviewer",
        )


@pytest.mark.anyio
async def test_approval_validates_missing_receipt(
    db_session: AsyncSession,
) -> None:
    document, _ = await create_document(db_session, with_receipt=False)

    with pytest.raises(DocumentApprovalValidationError) as error:
        await DocumentReviewService(db_session).approve_document(
            document.id,
            "Reviewer",
        )

    assert "A receipt is required." in error.value.errors


@pytest.mark.anyio
async def test_approval_rejects_missing_total(
    db_session: AsyncSession,
) -> None:
    document, _ = await create_document(db_session, total=None)

    with pytest.raises(DocumentApprovalValidationError) as error:
        await DocumentReviewService(db_session).approve_document(
            document.id,
            "Reviewer",
        )

    assert "A non-negative total is required." in error.value.errors


@pytest.mark.anyio
async def test_approval_rejects_document_without_items(
    db_session: AsyncSession,
) -> None:
    document, _ = await create_document(db_session, items=[])

    with pytest.raises(DocumentApprovalValidationError) as error:
        await DocumentReviewService(db_session).approve_document(
            document.id,
            "Reviewer",
        )

    assert "At least one receipt item is required." in error.value.errors


@pytest.mark.anyio
async def test_approval_rejects_inconsistent_cash_total_and_change(
    db_session: AsyncSession,
) -> None:
    document, _ = await create_document(db_session, change=100500)

    with pytest.raises(DocumentApprovalValidationError) as error:
        await DocumentReviewService(db_session).approve_document(
            document.id,
            "Reviewer",
        )

    assert "Cash, total, and change are inconsistent." in error.value.errors


@pytest.mark.anyio
async def test_approval_of_already_approved_document_is_idempotent(
    db_session: AsyncSession,
) -> None:
    approved_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    document, _ = await create_document(
        db_session,
        status=DocumentStatus.APPROVED,
        requires_review=False,
    )
    document_id = document.id
    document.approved_at = approved_at
    document.reviewed_at = approved_at
    document.reviewed_by = "Original reviewer"
    await db_session.commit()
    original_updated_at = document.updated_at

    response = await DocumentReviewService(db_session).approve_document(
        document_id,
        "Second reviewer",
    )
    persisted = await db_session.get(Document, document_id)

    assert response.message == "Document is already approved."
    assert response.approved_at == approved_at
    assert response.updated_at == original_updated_at
    assert persisted is not None
    assert persisted.reviewed_by == "Original reviewer"


@pytest.mark.anyio
async def test_correction_rolls_back_after_persistence_failure(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document, _ = await create_document(db_session)
    document_id = document.id
    correction = ReceiptCorrectionRequest.model_validate(correction_payload())

    async def fail_commit() -> None:
        raise SQLAlchemyError("database internals must not escape")

    monkeypatch.setattr(db_session, "commit", fail_commit)
    with pytest.raises(DocumentReviewPersistenceError) as error:
        await DocumentReviewService(db_session).update_receipt_correction(
            document_id,
            correction,
            "Reviewer",
        )
    assert "database internals" not in str(error.value)

    monkeypatch.undo()
    detail = await DocumentReviewService(db_session).get_document_detail(
        document_id
    )
    assert detail.receipt.merchant.name == "Original merchant"

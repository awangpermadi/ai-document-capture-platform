import asyncio
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from azure.ai.documentintelligence.models import (
    AnalyzeResult,
    AnalyzedDocument,
    CurrencyValue,
    DocumentField,
)
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool
from sqlalchemy.orm import selectinload

from app.database.session import get_db_session
from app.exceptions import DocumentReviewPersistenceError
from app.main import app
from app.models import Base, Document, DocumentStatus, ReceiptItemModel, ReceiptModel
from app.routes.documents import router as documents_router
from app.services.document_intelligence import DocumentIntelligenceError
from app.services.document_review import DocumentReviewService


def correction_body() -> dict[str, object]:
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
        "items": [
            {
                "id": None,
                "description_raw": "Reviewed item",
                "description_normalized": "Reviewed item",
                "quantity": 1,
                "unit_price": 75400,
                "total_price": 75400,
            }
        ],
    }


@pytest.fixture
def review_client(
    tmp_path: Path,
) -> Iterator[tuple[TestClient, async_sessionmaker[AsyncSession]]]:
    database_path = tmp_path / "document-review-api.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{database_path}",
        poolclass=NullPool,
    )

    async def create_schema() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(create_schema())
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    try:
        with TestClient(app) as client:
            yield client, session_factory
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        asyncio.run(engine.dispose())


def create_document(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    status: DocumentStatus = DocumentStatus.REVIEW_REQUIRED,
    change: float | None = 25100,
    item_lines: list[tuple[int, str]] | None = None,
) -> str:
    async def insert_document() -> str:
        document = Document(
            id=str(uuid4()),
            original_filename="receipt.pdf",
            stored_filename="stored-receipt.pdf",
            content_type="application/pdf",
            document_type="receipt",
            status=status,
            extraction_method="prebuilt_receipt",
            requires_review=status == DocumentStatus.REVIEW_REQUIRED,
            review_reasons='["Check receipt"]',
            raw_ocr_content="private OCR data",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        receipt = ReceiptModel(
            id=str(uuid4()),
            merchant_name="Original merchant",
            merchant_address="Old address",
            merchant_phone="555-0000",
            subtotal=77400,
            discount=2000,
            tax=7036,
            total=75400,
            cash=100500,
            change=change,
            currency="IDR",
            extraction_method="prebuilt_receipt",
        )
        lines = item_lines if item_lines is not None else [(1, "Original item")]
        for line_number, description in lines:
            receipt.items.append(
                ReceiptItemModel(
                    id=str(uuid4()),
                    line_number=line_number,
                    description_raw=description,
                    description_normalized=description,
                    quantity=1,
                    unit_price=75400,
                    total_price=75400,
                    confidence=0.9,
                    source="azure_prebuilt_receipt",
                )
            )
        document.receipt = receipt

        async with session_factory() as session:
            session.add(document)
            await session.commit()
        return document.id

    return asyncio.run(insert_document())


def create_round_trip_document(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[str, str]:
    document_id = create_document(session_factory)

    async def set_read_metadata() -> str:
        async with session_factory() as session:
            item = (
                await session.execute(
                    select(ReceiptItemModel)
                    .join(ReceiptModel)
                    .where(ReceiptModel.document_id == document_id)
                )
            ).scalar_one()
            item.description_raw = "POP MIE AYAM 75G"
            item.description_normalized = None
            item.quantity = 1
            item.unit_price = 4900
            item.total_price = 4900
            item.confidence = 0.981
            item.source = "azure_prebuilt_receipt"
            await session.commit()
            return item.id

    return document_id, asyncio.run(set_read_metadata())


def tlogomas_analyze_result() -> AnalyzeResult:
    labels = [
        ("HARGA JUAL", 0.1),
        ("TOTAL", 0.3),
        ("TUNAI", 0.5),
        ("KEMBALI", 0.7),
        ("ANDA HEMAT", 0.9),
    ]
    amounts = [
        ("77,400", 0.1),
        ("75,400", 0.3),
        ("100,500", 0.5),
        ("25,100", 0.7),
        ("2,000", 0.9),
    ]

    def line(text: str, x: float, y: float) -> SimpleNamespace:
        return SimpleNamespace(
            content=text,
            polygon=[
                SimpleNamespace(x=x, y=y),
                SimpleNamespace(x=x + 1, y=y),
                SimpleNamespace(x=x + 1, y=y + 0.1),
                SimpleNamespace(x=x, y=y + 0.1),
            ],
        )

    content = (
        "HARGA JUAL\nTOTAL\nTUNAI\nKEMBALI\nANDA HEMAT\n"
        "77,400\n75,400\n100,500\n25,100\n2,000\n"
        "DPP= 70,364 PPN= 7,036"
    )
    fields = {
        "MerchantName": DocumentField(value_string="Tlogomas"),
        "Subtotal": DocumentField(
            value_currency=CurrencyValue(amount=77400, currency_code="IDR")
        ),
        "TotalTax": DocumentField(
            value_currency=CurrencyValue(amount=7036, currency_code="IDR")
        ),
        "Total": DocumentField(
            value_currency=CurrencyValue(amount=75400, currency_code="IDR")
        ),
        "Items": DocumentField(
            value_array=[
                DocumentField(
                    confidence=0.99,
                    value_object={
                        "Description": DocumentField(
                            value_string="Receipt item"
                        ),
                        "Quantity": DocumentField(value_number=1),
                        "Price": DocumentField(value_number=75400),
                        "TotalPrice": DocumentField(value_number=75400),
                    },
                )
            ]
        ),
    }
    return AnalyzeResult(
        content=content,
        pages=[
            SimpleNamespace(
                lines=[
                    *(line(text, 0, y) for text, y in labels),
                    *(line(text, 2, y) for text, y in amounts),
                    line("DPP= 70,364 PPN= 7,036", 0, 1.1),
                ]
            )
        ],
        documents=[AnalyzedDocument(confidence=0.99, fields=fields)],
    )


def test_get_documents_returns_list(review_client) -> None:
    client, session_factory = review_client
    document_id = create_document(session_factory)

    response = client.get("/documents")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [document_id]
    assert "raw_ocr_content" not in response.json()[0]


def test_get_documents_filters_uppercase_review_required(review_client) -> None:
    client, session_factory = review_client
    review_id = create_document(session_factory)
    create_document(session_factory, status=DocumentStatus.APPROVED)

    response = client.get("/documents?status=REVIEW_REQUIRED")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [review_id]


def test_get_document_returns_receipt_and_ordered_items(review_client) -> None:
    client, session_factory = review_client
    document_id = create_document(
        session_factory,
        item_lines=[(2, "Second line"), (1, "First line")],
    )

    response = client.get(f"/documents/{document_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["receipt"]["merchant"]["name"] == "Original merchant"
    assert [
        item["description_normalized"] for item in body["receipt"]["items"]
    ] == ["First line", "Second line"]
    assert "raw_ocr_content" not in body
    assert "private OCR data" not in response.text


def test_unknown_document_returns_404(review_client) -> None:
    client, session_factory = review_client

    response = client.get("/documents/not-found")

    assert response.status_code == 404
    assert response.json()["detail"] == "Document not found."


def test_put_correction_updates_receipt_and_items(review_client) -> None:
    client, session_factory = review_client
    document_id = create_document(session_factory)

    response = client.put(
        f"/documents/{document_id}/receipt",
        headers={"X-Reviewed-By": "Reviewer"},
        json=correction_body(),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == DocumentStatus.REVIEW_REQUIRED.value
    assert body["reviewed_by"] == "Reviewer"
    assert body["receipt"]["merchant"]["name"] == "Reviewed merchant"
    assert body["receipt"]["transaction"] == {
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
    }
    assert body["receipt"]["items"][0]["description_normalized"] == "Reviewed item"
    assert body["receipt"]["items"][0]["source"] == "human_review"


def test_put_round_trip_preserves_metadata_for_unchanged_item(
    review_client,
) -> None:
    client, session_factory = review_client
    document_id, item_id = create_round_trip_document(session_factory)
    receipt = client.get(f"/documents/{document_id}").json()["receipt"]

    assert receipt["items"][0]["id"] == item_id
    assert receipt["items"][0]["confidence"] == 0.981
    assert receipt["items"][0]["source"] == "azure_prebuilt_receipt"

    response = client.put(
        f"/documents/{document_id}/receipt",
        headers={"X-Reviewed-By": "test-reviewer"},
        json=receipt,
    )

    assert response.status_code == 200, response.text

    async def get_item_metadata() -> tuple[float | None, str]:
        async with session_factory() as session:
            item = await session.get(ReceiptItemModel, item_id)
            assert item is not None
            return item.confidence, item.source

    assert asyncio.run(get_item_metadata()) == (
        0.981,
        "azure_prebuilt_receipt",
    )


def test_put_changed_existing_item_clears_server_metadata(
    review_client,
) -> None:
    client, session_factory = review_client
    document_id, item_id = create_round_trip_document(session_factory)
    receipt = client.get(f"/documents/{document_id}").json()["receipt"]
    receipt["items"][0]["description_normalized"] = "Pop Mie Ayam 75g"

    response = client.put(
        f"/documents/{document_id}/receipt",
        headers={"X-Reviewed-By": "test-reviewer"},
        json=receipt,
    )

    assert response.status_code == 200, response.text
    assert (
        response.json()["receipt"]["items"][0]["description_normalized"]
        == "Pop Mie Ayam 75g"
    )

    async def get_item_metadata() -> tuple[str | None, float | None, str]:
        async with session_factory() as session:
            item = await session.get(ReceiptItemModel, item_id)
            assert item is not None
            return (
                item.description_normalized,
                item.confidence,
                item.source,
            )

    assert asyncio.run(get_item_metadata()) == (
        "Pop Mie Ayam 75g",
        None,
        "human_review",
    )


def test_put_never_trusts_client_item_metadata(
    review_client,
) -> None:
    client, session_factory = review_client
    document_id, item_id = create_round_trip_document(session_factory)
    receipt = client.get(f"/documents/{document_id}").json()["receipt"]
    receipt["items"][0]["description_raw"] = "Client changed description"
    receipt["items"][0]["confidence"] = 1.0
    receipt["items"][0]["source"] = "trusted_by_admin"

    response = client.put(
        f"/documents/{document_id}/receipt",
        headers={"X-Reviewed-By": "test-reviewer"},
        json=receipt,
    )

    assert response.status_code == 200, response.text

    async def get_item_metadata() -> tuple[float | None, str]:
        async with session_factory() as session:
            item = await session.get(ReceiptItemModel, item_id)
            assert item is not None
            return item.confidence, item.source

    assert asyncio.run(get_item_metadata()) == (None, "human_review")


def test_put_new_item_gets_server_managed_metadata(
    review_client,
) -> None:
    client, session_factory = review_client
    document_id = create_document(session_factory)
    body = correction_body()
    body["items"][0]["confidence"] = 0.981  # type: ignore[index]
    body["items"][0]["source"] = "trusted_by_admin"  # type: ignore[index]

    response = client.put(
        f"/documents/{document_id}/receipt",
        headers={"X-Reviewed-By": "test-reviewer"},
        json=body,
    )

    assert response.status_code == 200, response.text
    new_item_id = response.json()["receipt"]["items"][0]["id"]

    async def get_item_metadata() -> tuple[float | None, str]:
        async with session_factory() as session:
            item = await session.get(ReceiptItemModel, new_item_id)
            assert item is not None
            return item.confidence, item.source

    assert asyncio.run(get_item_metadata()) == (None, "human_review")


def test_put_rejects_unknown_item_fields(review_client) -> None:
    client, session_factory = review_client
    document_id = create_document(session_factory)
    body = correction_body()
    body["items"][0]["random_field"] = "abc"  # type: ignore[index]

    response = client.put(
        f"/documents/{document_id}/receipt",
        headers={"X-Reviewed-By": "test-reviewer"},
        json=body,
    )

    assert response.status_code == 422
    assert any(
        error["type"] == "extra_forbidden"
        and error["loc"] == ["body", "items", 0, "random_field"]
        for error in response.json()["detail"]
    )


def test_put_accepts_complete_tlogomas_receipt_read_payload(
    review_client,
) -> None:
    client, session_factory = review_client
    document_id, item_id = create_round_trip_document(session_factory)
    receipt = client.get(f"/documents/{document_id}").json()["receipt"]
    receipt["merchant"]["name"] = "TLOGOMAS 44 MALANG"
    receipt["transaction"].update(
        {
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
        }
    )

    response = client.put(
        f"/documents/{document_id}/receipt",
        headers={"X-Reviewed-By": "test-reviewer"},
        json=receipt,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["receipt"]["merchant"]["name"] == "TLOGOMAS 44 MALANG"
    assert body["receipt"]["transaction"]["subtotal"] == 77400
    assert body["receipt"]["transaction"]["discount"] == 2000
    assert body["receipt"]["transaction"]["tax"] == 7036
    assert body["receipt"]["transaction"]["total"] == 75400
    assert body["receipt"]["transaction"]["cash"] == 100500
    assert body["receipt"]["transaction"]["change"] == 25100
    assert body["receipt"]["transaction"]["currency"] == "IDR"
    assert body["receipt"]["items"][0]["id"] == item_id
    assert body["receipt"]["items"][0]["confidence"] == 0.981
    assert body["receipt"]["items"][0]["source"] == "azure_prebuilt_receipt"

    async def get_persisted_receipt() -> tuple[float, float, float, float, float, float]:
        async with session_factory() as session:
            receipt_model = (
                await session.execute(
                    select(ReceiptModel).where(
                        ReceiptModel.document_id == document_id
                    )
                )
            ).scalar_one()
            return (
                receipt_model.subtotal,
                receipt_model.discount,
                receipt_model.tax,
                receipt_model.total,
                receipt_model.cash,
                receipt_model.change,
            )

    assert asyncio.run(get_persisted_receipt()) == (
        77400,
        2000,
        7036,
        75400,
        100500,
        25100,
    )


def test_process_extracts_persists_and_returns_tlogomas_values(
    review_client,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, session_factory = review_client
    upload_directory = tmp_path / "uploads"
    monkeypatch.setattr(
        "app.routes.documents.UPLOAD_DIRECTORY",
        upload_directory,
    )
    azure_result = tlogomas_analyze_result()

    class MockAzureDocumentIntelligenceService:
        calls = 0

        def analyze_document(self, document_content: bytes) -> AnalyzeResult:
            self.calls += 1
            assert document_content == b"receipt"
            return azure_result

    mock_azure = MockAzureDocumentIntelligenceService()
    monkeypatch.setattr(
        "app.services.receipt_extraction.AzureDocumentIntelligenceService",
        lambda: mock_azure,
    )

    response = client.post(
        "/documents/process",
        files={
            "file": (
                "tlogomas.pdf",
                b"receipt",
                "application/pdf",
            )
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["document_id"]
    assert body["status"] == "EXTRACTED"
    assert body["requires_review"] is False
    assert body["review_reasons"] == []
    assert body["receipt"]["transaction"] == {
        "date": None,
        "time": None,
        "subtotal": 77400,
        "discount": 2000,
        "tax": 7036,
        "tip": None,
        "total": 75400,
        "cash": 100500,
        "change": 25100,
        "currency": "IDR",
    }
    assert mock_azure.calls == 1
    assert "raw_ocr_content" not in body
    assert "DPP= 70,364" not in response.text

    saved_files = list(upload_directory.iterdir())
    assert len(saved_files) == 1
    assert saved_files[0].name.endswith(".pdf")
    assert saved_files[0].read_bytes() == b"receipt"

    async def verify_database() -> dict[str, object]:
        async with session_factory() as session:
            document = (
                await session.execute(
                    select(Document)
                    .where(Document.id == body["document_id"])
                    .options(
                        selectinload(Document.receipt).selectinload(
                            ReceiptModel.items
                        )
                    )
                )
            ).scalar_one()
            receipt_count = await session.scalar(
                select(func.count()).select_from(ReceiptModel)
            )
            item_count = await session.scalar(
                select(func.count()).select_from(ReceiptItemModel)
            )
            assert document.receipt is not None
            return {
                "document_status": document.status,
                "requires_review": document.requires_review,
                "raw_ocr_content": document.raw_ocr_content,
                "receipt_count": receipt_count,
                "item_count": item_count,
                "subtotal": document.receipt.subtotal,
                "discount": document.receipt.discount,
                "tax": document.receipt.tax,
                "total": document.receipt.total,
                "cash": document.receipt.cash,
                "change": document.receipt.change,
                "currency": document.receipt.currency,
                "item_line_number": document.receipt.items[0].line_number,
            }

    database_values = asyncio.run(verify_database())
    assert database_values == {
        "document_status": DocumentStatus.EXTRACTED,
        "requires_review": False,
        "raw_ocr_content": azure_result.content,
        "receipt_count": 1,
        "item_count": 1,
        "subtotal": 77400,
        "discount": 2000,
        "tax": 7036,
        "total": 75400,
        "cash": 100500,
        "change": 25100,
        "currency": "IDR",
        "item_line_number": 1,
    }


def test_put_correction_requires_reviewer_header(review_client) -> None:
    client, session_factory = review_client
    document_id = create_document(session_factory)

    response = client.put(
        f"/documents/{document_id}/receipt",
        json=correction_body(),
    )

    assert response.status_code == 422


def test_put_correction_rejects_whitespace_reviewer_header(review_client) -> None:
    client, session_factory = review_client
    document_id = create_document(session_factory)

    response = client.put(
        f"/documents/{document_id}/receipt",
        headers={"X-Reviewed-By": "   "},
        json=correction_body(),
    )

    assert response.status_code == 422


def test_put_correction_rejects_approved_document(review_client) -> None:
    client, session_factory = review_client
    document_id = create_document(
        session_factory,
        status=DocumentStatus.APPROVED,
    )

    response = client.put(
        f"/documents/{document_id}/receipt",
        headers={"X-Reviewed-By": "Reviewer"},
        json=correction_body(),
    )

    assert response.status_code == 409


def test_post_approve_changes_status(review_client) -> None:
    client, session_factory = review_client
    document_id = create_document(session_factory)

    response = client.post(
        f"/documents/{document_id}/approve",
        json={"reviewed_by": "Reviewer", "confirmation": True},
    )

    assert response.status_code == 200
    assert response.json()["status"] == DocumentStatus.APPROVED.value


def test_post_approve_rejects_false_confirmation(review_client) -> None:
    client, session_factory = review_client
    document_id = create_document(session_factory)

    response = client.post(
        f"/documents/{document_id}/approve",
        json={"reviewed_by": "Reviewer", "confirmation": False},
    )

    assert response.status_code == 422


def test_post_approve_rejects_inconsistent_payment(review_client) -> None:
    client, session_factory = review_client
    document_id = create_document(session_factory, change=100500)

    response = client.post(
        f"/documents/{document_id}/approve",
        json={"reviewed_by": "Reviewer", "confirmation": True},
    )

    assert response.status_code == 422
    assert "Cash, total, and change are inconsistent." in (
        response.json()["detail"]["reasons"]
    )


def test_post_approve_is_idempotent(review_client) -> None:
    client, session_factory = review_client
    document_id = create_document(session_factory)
    payload = {"reviewed_by": "Reviewer", "confirmation": True}

    first_response = client.post(
        f"/documents/{document_id}/approve",
        json=payload,
    )
    second_response = client.post(
        f"/documents/{document_id}/approve",
        json=payload,
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert second_response.json()["message"] == "Document is already approved."
    assert (
        second_response.json()["approved_at"]
        == first_response.json()["approved_at"]
    )


def test_document_routes_are_registered_once_and_not_shadowed() -> None:
    included_routers = [
        route
        for route in app.routes
        if getattr(route, "original_router", None) is documents_router
    ]
    assert len(included_routers) == 1
    registered_routes = included_routers[0].original_router.routes
    route_entries = [
        (index, route.path, method)
        for index, route in enumerate(registered_routes)
        for method in (route.methods or set())
    ]

    expected_routes = [
        ("/documents", "GET"),
        ("/documents/{document_id}", "GET"),
        ("/documents/{document_id}", "DELETE"),
        ("/documents/{document_id}/receipt", "PUT"),
        ("/documents/{document_id}/approve", "POST"),
        ("/documents/process", "POST"),
        ("/documents/upload", "POST"),
        ("/documents/analyze", "POST"),
        ("/documents/debug-analysis", "POST"),
    ]
    for path, method in expected_routes:
        assert sum(
            route_path == path and route_method == method
            for _, route_path, route_method in route_entries
        ) == 1

    static_indexes = [
        index
        for index, route_path, method in route_entries
        if method == "POST"
        and route_path
        in {
            "/documents/upload",
            "/documents/analyze",
            "/documents/debug-analysis",
            "/documents/process",
        }
    ]
    detail_index = next(
        index
        for index, route_path, method in route_entries
        if route_path == "/documents/{document_id}" and method == "GET"
    )
    assert static_indexes and max(static_indexes) < detail_index

def test_persistence_errors_return_safe_http_500(
    review_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, session_factory = review_client
    document_id = create_document(session_factory)

    async def fail_approval(
        self: DocumentReviewService,
        document_id: str,
        reviewed_by: str,
    ) -> None:
        raise DocumentReviewPersistenceError()

    monkeypatch.setattr(DocumentReviewService, "approve_document", fail_approval)
    response = client.post(
        f"/documents/{document_id}/approve",
        json={"reviewed_by": "Reviewer", "confirmation": True},
    )

    assert response.status_code == 500
    assert "database" not in response.text.lower()
    assert response.json()["detail"] == (
        "Document review operation could not be completed."
    )


def test_unexpected_errors_are_logged_and_return_generic_http_500(
    review_client,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, session_factory = review_client
    document_id = create_document(session_factory)

    async def fail_approval(
        self: DocumentReviewService,
        document_id: str,
        reviewed_by: str,
    ) -> None:
        raise RuntimeError("sensitive internal details")

    monkeypatch.setattr(DocumentReviewService, "approve_document", fail_approval)
    response = client.post(
        f"/documents/{document_id}/approve",
        json={"reviewed_by": "Reviewer", "confirmation": True},
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "An unexpected server error occurred."
    assert "sensitive internal details" not in response.text
    assert "sensitive internal details" in caplog.text


@pytest.mark.parametrize(
    ("content_type", "content", "expected_status"),
    [
        ("text/plain", b"receipt", 415),
        ("application/pdf", b"", 400),
        ("application/pdf", b"x" * (10 * 1024 * 1024 + 1), 413),
    ],
)
def test_process_validates_uploads(
    review_client,
    content_type: str,
    content: bytes,
    expected_status: int,
) -> None:
    client, _ = review_client

    response = client.post(
        "/documents/process",
        files={"file": ("receipt.pdf", content, content_type)},
    )

    assert response.status_code == expected_status


def test_process_cleans_up_file_when_extraction_fails(
    review_client,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = review_client
    upload_directory = tmp_path / "uploads"
    monkeypatch.setattr(
        "app.routes.documents.UPLOAD_DIRECTORY",
        upload_directory,
    )

    class FailedAzureDocumentIntelligenceService:
        def analyze_document(self, document_content: bytes) -> AnalyzeResult:
            raise DocumentIntelligenceError("private Azure error")

    monkeypatch.setattr(
        "app.services.receipt_extraction.AzureDocumentIntelligenceService",
        FailedAzureDocumentIntelligenceService,
    )

    response = client.post(
        "/documents/process",
        files={
            "file": (
                "tlogomas.pdf",
                b"receipt",
                "application/pdf",
            )
        },
    )

    assert response.status_code == 502
    assert "private Azure error" not in response.text
    assert list(upload_directory.iterdir()) == []


def test_process_cleans_up_file_when_persistence_fails(
    review_client,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, session_factory = review_client
    upload_directory = tmp_path / "uploads"
    monkeypatch.setattr(
        "app.routes.documents.UPLOAD_DIRECTORY",
        upload_directory,
    )
    azure_result = tlogomas_analyze_result()

    class MockAzureDocumentIntelligenceService:
        def analyze_document(self, document_content: bytes) -> AnalyzeResult:
            return azure_result

    original_commit = AsyncSession.commit

    async def fail_commit(self: AsyncSession) -> None:
        raise SQLAlchemyError("database internals must not escape")

    monkeypatch.setattr(
        "app.services.receipt_extraction.AzureDocumentIntelligenceService",
        MockAzureDocumentIntelligenceService,
    )
    monkeypatch.setattr(AsyncSession, "commit", fail_commit)

    response = client.post(
        "/documents/process",
        files={
            "file": (
                "tlogomas.pdf",
                b"receipt",
                "application/pdf",
            )
        },
    )

    assert response.status_code == 500
    assert "database" not in response.text.lower()
    assert list(upload_directory.iterdir()) == []

    monkeypatch.setattr(AsyncSession, "commit", original_commit)

    async def get_document_count() -> int:
        async with session_factory() as session:
            return await session.scalar(
                select(func.count()).select_from(Document)
            ) or 0

    assert asyncio.run(get_document_count()) == 0


def set_stored_filename(
    session_factory: async_sessionmaker[AsyncSession],
    document_id: str,
    stored_filename: str,
) -> None:
    async def update() -> None:
        async with session_factory() as session:
            document = await session.get(Document, document_id)
            assert document is not None
            document.stored_filename = stored_filename
            await session.commit()

    asyncio.run(update())


def document_record_counts(
    session_factory: async_sessionmaker[AsyncSession],
    document_id: str,
) -> tuple[int, int, int]:
    async def query_counts() -> tuple[int, int, int]:
        async with session_factory() as session:
            document_count = await session.scalar(
                select(func.count())
                .select_from(Document)
                .where(Document.id == document_id)
            )
            receipt_count = await session.scalar(
                select(func.count())
                .select_from(ReceiptModel)
                .where(ReceiptModel.document_id == document_id)
            )
            item_count = await session.scalar(
                select(func.count())
                .select_from(ReceiptItemModel)
                .join(ReceiptModel)
                .where(ReceiptModel.document_id == document_id)
            )
            return (
                int(document_count or 0),
                int(receipt_count or 0),
                int(item_count or 0),
            )

    return asyncio.run(query_counts())


@pytest.mark.parametrize(
    "status",
    [
        DocumentStatus.UPLOADED,
        DocumentStatus.PROCESSING,
        DocumentStatus.EXTRACTED,
        DocumentStatus.REVIEW_REQUIRED,
        DocumentStatus.FAILED,
    ],
)
def test_delete_document_removes_record_relations_and_uploaded_file(
    review_client,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: DocumentStatus,
) -> None:
    client, session_factory = review_client
    upload_directory = tmp_path / "uploads"
    upload_directory.mkdir()
    monkeypatch.setattr(
        "app.services.document_review.UPLOAD_DIRECTORY",
        upload_directory,
    )
    document_id = create_document(session_factory, status=status)
    stored_file = upload_directory / "stored-receipt.pdf"
    stored_file.write_bytes(b"receipt")

    response = client.delete(f"/documents/{document_id}")

    assert response.status_code == 200
    assert response.json() == {
        "document_id": document_id,
        "status": "DELETED",
        "message": "Document deleted successfully.",
        "warning": None,
    }
    assert not stored_file.exists()
    assert document_record_counts(session_factory, document_id) == (0, 0, 0)


def test_delete_document_succeeds_when_uploaded_file_is_missing(
    review_client,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, session_factory = review_client
    upload_directory = tmp_path / "uploads"
    upload_directory.mkdir()
    monkeypatch.setattr(
        "app.services.document_review.UPLOAD_DIRECTORY",
        upload_directory,
    )
    document_id = create_document(session_factory, status=DocumentStatus.EXTRACTED)

    response = client.delete(f"/documents/{document_id}")

    assert response.status_code == 200
    assert response.json()["warning"] == "The uploaded file was already missing."
    assert "already missing" in caplog.text
    assert document_record_counts(session_factory, document_id) == (0, 0, 0)


def test_delete_unknown_document_returns_404(review_client) -> None:
    client, _ = review_client

    response = client.delete("/documents/not-found")

    assert response.status_code == 404
    assert response.json()["detail"] == "Document not found."


def test_delete_approved_document_returns_409_and_keeps_record(
    review_client,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, session_factory = review_client
    upload_directory = tmp_path / "uploads"
    upload_directory.mkdir()
    monkeypatch.setattr(
        "app.services.document_review.UPLOAD_DIRECTORY",
        upload_directory,
    )
    document_id = create_document(
        session_factory,
        status=DocumentStatus.APPROVED,
    )
    stored_file = upload_directory / "stored-receipt.pdf"
    stored_file.write_bytes(b"receipt")

    response = client.delete(f"/documents/{document_id}")

    assert response.status_code == 409
    assert response.json()["detail"] == "Approved documents cannot be deleted."
    assert stored_file.read_bytes() == b"receipt"
    assert document_record_counts(session_factory, document_id) == (1, 1, 1)

    async def read_status() -> DocumentStatus | None:
        async with session_factory() as session:
            document = await session.get(Document, document_id)
            return document.status if document is not None else None

    assert asyncio.run(read_status()) == DocumentStatus.APPROVED


def test_delete_does_not_remove_file_outside_upload_directory(
    review_client,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, session_factory = review_client
    upload_directory = tmp_path / "uploads"
    upload_directory.mkdir()
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("keep", encoding="utf-8")
    monkeypatch.setattr(
        "app.services.document_review.UPLOAD_DIRECTORY",
        upload_directory,
    )
    document_id = create_document(session_factory, status=DocumentStatus.EXTRACTED)
    set_stored_filename(session_factory, document_id, "../outside.txt")

    response = client.delete(f"/documents/{document_id}")

    assert response.status_code == 200
    assert response.json()["warning"] == "The uploaded file could not be removed."
    assert str(tmp_path) not in response.text
    assert outside_file.read_text(encoding="utf-8") == "keep"
    assert document_record_counts(session_factory, document_id) == (0, 0, 0)


def test_delete_database_failure_keeps_file_and_record(
    review_client,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, session_factory = review_client
    upload_directory = tmp_path / "uploads"
    upload_directory.mkdir()
    monkeypatch.setattr(
        "app.services.document_review.UPLOAD_DIRECTORY",
        upload_directory,
    )
    document_id = create_document(session_factory, status=DocumentStatus.EXTRACTED)
    stored_file = upload_directory / "stored-receipt.pdf"
    stored_file.write_bytes(b"receipt")

    async def fail_commit(self: AsyncSession) -> None:
        raise SQLAlchemyError("private database detail")

    monkeypatch.setattr(AsyncSession, "commit", fail_commit)
    response = client.delete(f"/documents/{document_id}")

    assert response.status_code == 500
    assert "private database detail" not in response.text
    assert response.json()["detail"] == (
        "Document review operation could not be completed."
    )
    assert stored_file.read_bytes() == b"receipt"
    assert document_record_counts(session_factory, document_id) == (1, 1, 1)


def test_delete_file_failure_returns_safe_warning_after_commit(
    review_client,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, session_factory = review_client
    upload_directory = tmp_path / "uploads"
    upload_directory.mkdir()
    monkeypatch.setattr(
        "app.services.document_review.UPLOAD_DIRECTORY",
        upload_directory,
    )
    document_id = create_document(session_factory, status=DocumentStatus.EXTRACTED)
    stored_file = upload_directory / "stored-receipt.pdf"
    stored_file.write_bytes(b"receipt")
    original_unlink = Path.unlink

    def fail_target_unlink(
        path: Path,
        *args: object,
        **kwargs: object,
    ) -> None:
        if path == stored_file.resolve():
            raise OSError("private filesystem detail")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_target_unlink)
    response = client.delete(f"/documents/{document_id}")

    assert response.status_code == 200
    assert response.json()["warning"] == "The uploaded file could not be removed."
    assert "private filesystem detail" not in response.text
    assert document_record_counts(session_factory, document_id) == (0, 0, 0)
    assert stored_file.read_bytes() == b"receipt"


def test_process_marks_unvalidated_receipt_for_review(
    review_client,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, session_factory = review_client
    upload_directory = tmp_path / "uploads"
    monkeypatch.setattr(
        "app.routes.documents.UPLOAD_DIRECTORY",
        upload_directory,
    )

    class MockAzureDocumentIntelligenceService:
        def analyze_document(self, document_content: bytes) -> AnalyzeResult:
            return AnalyzeResult(content="", documents=[])

    monkeypatch.setattr(
        "app.services.receipt_extraction.AzureDocumentIntelligenceService",
        MockAzureDocumentIntelligenceService,
    )
    response = client.post(
        "/documents/process",
        files={
            "file": (
                "unknown.pdf",
                b"document",
                "application/pdf",
            )
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "REVIEW_REQUIRED"
    assert body["requires_review"] is True
    assert body["review_reasons"]

    async def get_document_status() -> tuple[DocumentStatus, bool]:
        async with session_factory() as session:
            document = await session.get(Document, body["document_id"])
            assert document is not None
            return document.status, document.requires_review

    assert asyncio.run(get_document_status()) == (
        DocumentStatus.REVIEW_REQUIRED,
        True,
    )

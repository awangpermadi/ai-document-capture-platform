import unittest
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from azure.ai.documentintelligence.models import (
    AnalyzeResult,
    AnalyzedDocument,
    CurrencyValue,
    DocumentField,
)
from fastapi.testclient import TestClient

from app.main import app
from app.routes.documents import router as documents_router
from app.schemas.receipt import Merchant, Receipt, ReceiptItem, Transaction
from app.services.receipt_merger import ReceiptMerger
from app.services.receipt_text_parser import ReceiptTextParser


@pytest.mark.parametrize(
    "raw_content",
    [
        (
            "TOTAL : 75,400\n"
            "TUNAI : 100,500\n"
            "KEMBALI : 25,100\n"
            "ANDA HEMAT : 2,000"
        ),
        (
            "TOTAL\n75,400\n"
            "TUNAI\n100,500\n"
            "KEMBALI\n25,100\n"
            "ANDA HEMAT\n2,000"
        ),
        (
            "TOTAL :\n75,400\n"
            "TUNAI :\n100,500\n"
            "KEMBALI :\n25,100\n"
            "ANDA HEMAT :\n2,000"
        ),
        (
            "TOTAL:75.400\n"
            "TUNAI=Rp 100.500\n"
            "KEMBALI=25.100\n"
            "DISKON=(2.000)"
        ),
    ],
)
def test_summary_values_parse_across_layouts(raw_content: str) -> None:
    print("OCR content repr:", repr(raw_content))
    receipt = ReceiptTextParser.parse(raw_content)

    assert receipt.transaction.total == 75_400
    assert receipt.transaction.cash == 100_500
    assert receipt.transaction.change == 25_100
    assert receipt.transaction.discount == 2_000


def test_tax_parser_does_not_capture_dpp_value() -> None:
    raw_content = "DPP= 70,364 PPN= 7,036"
    receipt = ReceiptTextParser.parse(raw_content)

    assert receipt.transaction.tax == 7_036


def test_geometry_maps_values_when_ocr_lists_labels_before_amounts() -> None:
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

    def make_line(text: str, x1: float, y: float) -> SimpleNamespace:
        return SimpleNamespace(
            content=text,
            polygon=[
                SimpleNamespace(x=x1, y=y),
                SimpleNamespace(x=x1 + 1, y=y),
                SimpleNamespace(x=x1 + 1, y=y + 0.1),
                SimpleNamespace(x=x1, y=y + 0.1),
            ],
        )

    ocr_lines = [
        make_line(label, 0, y) for label, y in labels
    ] + [
        make_line(amount, 2, y) for amount, y in amounts
    ] + [
        make_line("DPP= 70,364 PPN= 7,036", 0, 1.1)
    ]
    pages = [SimpleNamespace(lines=ocr_lines)]
    raw_content = (
        "HARGA JUAL\nTOTAL\nTUNAI\nKEMBALI\nANDA HEMAT\n"
        "77,400\n75,400\n100,500\n25,100\n2,000\n"
        "DPP= 70,364 PPN= 7,036"
    )
    print("OCR content repr:", repr(raw_content))
    print(
        "OCR line structure repr:",
        repr([line.content for line in ocr_lines]),
    )
    for line_index, line in enumerate(ocr_lines):
        print(f"OCR line {line_index}: {line.content!r}")

    receipt = ReceiptTextParser.parse(raw_content, pages=pages)

    assert receipt.transaction.subtotal == 77_400
    assert receipt.transaction.total == 75_400
    assert receipt.transaction.cash == 100_500
    assert receipt.transaction.change == 25_100
    assert receipt.transaction.discount == 2_000
    assert receipt.transaction.tax == 7_036


def test_labels_first_without_geometry_do_not_shift_values() -> None:
    raw_content = (
        "TOTAL\nTUNAI\nKEMBALI\nANDA HEMAT\n"
        "75,400\n100,500\n25,100\n2,000"
    )
    receipt = ReceiptTextParser.parse(raw_content)

    assert receipt.transaction.total is None
    assert receipt.transaction.cash is None
    assert receipt.transaction.change is None
    assert receipt.transaction.discount is None


class ReceiptTextParserTests(unittest.TestCase):
    def test_parses_indonesian_payment_and_change_labels(self) -> None:
        cash_examples = (
            "TUNAI : 100,500",
            "TUNAI:100,500",
            "TUNAI 100,500",
            "TUNAI = 100,500",
            "TUNAI : Rp 100,500",
            "CASH = Rp 100,500",
            "BAYAR 100,500",
            "BAYAR (CASH) : Rp. 100,500",
        )
        change_examples = (
            "KEMBALI : 25,100",
            "CHANGE = Rp 25,100",
        )

        for line in cash_examples:
            with self.subTest(line=line):
                self.assertEqual(
                    ReceiptTextParser.extract_summary_value([line], "cash"),
                    100_500,
                )

        for line in change_examples:
            with self.subTest(line=line):
                self.assertEqual(
                    ReceiptTextParser.extract_summary_value(
                        [line],
                        "change",
                    ),
                    25_100,
                )

    def test_parses_tlogomas_summary_values(self) -> None:
        raw_content = """
TOTAL : 75,400
TUNAI :
100,500
KEMBALI
25,100
ANDA HEMAT :
2,000
DPP= 70,364 PPN= 7,036
"""
        print("OCR content repr:", repr(raw_content))
        parsed = ReceiptTextParser.parse(raw_content)

        self.assertEqual(
            parsed.transaction.total,
            75_400,
        )
        self.assertEqual(
            parsed.transaction.cash,
            100_500,
        )
        self.assertEqual(
            parsed.transaction.change,
            25_100,
        )
        self.assertEqual(
            parsed.transaction.discount,
            2_000,
        )
        self.assertEqual(
            parsed.transaction.tax,
            7_036,
        )

    def test_parses_other_indonesian_summary_labels_and_amount_formats(self) -> None:
        self.assertEqual(ReceiptTextParser.parse_number("75,400"), 75_400)
        self.assertEqual(ReceiptTextParser.parse_number("75.400"), 75_400)
        self.assertEqual(ReceiptTextParser.parse_number("Rp 75.400"), 75_400)
        self.assertEqual(ReceiptTextParser.parse_number("(2,000)"), -2_000)

        self.assertEqual(
            ReceiptTextParser.extract_summary_value(
                ["DISKON : (2,000)"],
                "discount",
            ),
            2_000,
        )
        self.assertEqual(
            ReceiptTextParser.extract_summary_value(
                ["DISKON = 2,000"],
                "discount",
            ),
            2_000,
        )
        self.assertEqual(
            ReceiptTextParser.extract_summary_value(
                ["DISCOUNT = 2,000"],
                "discount",
            ),
            2_000,
        )
        self.assertEqual(
            ReceiptTextParser.extract_summary_value(
                ["HARGA JUAL: 75.400"],
                "subtotal",
            ),
            75_400,
        )
        self.assertEqual(
            ReceiptTextParser.extract_summary_value(
                ["TAX = Rp 7,036"],
                "tax",
            ),
            7_036,
        )


class ReceiptMergerTests(unittest.TestCase):
    def test_fallback_only_fills_none_fields(self) -> None:
        primary = Receipt(
            merchant=Merchant(name="Azure merchant", phone="Azure phone"),
            transaction=Transaction(
                subtotal=77_400,
                total=75_400,
                tax=7_036,
            ),
            items=[],
        )
        fallback = Receipt(
            merchant=Merchant(name="OCR merchant", phone="OCR phone"),
            transaction=Transaction(
                discount=2_000,
                total=80_000,
                cash=100_500,
                change=25_100,
            ),
            items=[ReceiptItem(description_raw="OCR item", quantity=1)],
            extraction_method="ocr_text_fallback",
        )

        merged = ReceiptMerger.merge(primary, fallback)

        self.assertEqual(merged.merchant.name, "Azure merchant")
        self.assertEqual(merged.merchant.phone, "Azure phone")
        self.assertEqual(merged.transaction.subtotal, 77_400)
        self.assertEqual(merged.transaction.total, 75_400)
        self.assertEqual(merged.transaction.tax, 7_036)
        self.assertEqual(merged.transaction.discount, 2_000)
        self.assertEqual(merged.transaction.cash, 100_500)
        self.assertEqual(merged.transaction.change, 25_100)
        self.assertEqual(merged.items[0].description_raw, "OCR item")


class ReceiptResponseSchemaTests(unittest.TestCase):
    def test_analyze_response_includes_all_transaction_fields(self) -> None:
        openapi = app.openapi()
        response_schema = openapi["paths"]["/documents/analyze"]["post"][
            "responses"
        ]["200"]["content"]["application/json"]["schema"]
        receipt_name = response_schema["$ref"].rsplit("/", 1)[-1]
        transaction_ref = openapi["components"]["schemas"][receipt_name][
            "properties"
        ]["transaction"]["$ref"]
        transaction_name = transaction_ref.rsplit("/", 1)[-1]
        transaction_fields = openapi["components"]["schemas"][
            transaction_name
        ]["properties"]

        self.assertTrue(
            {
                "subtotal",
                "discount",
                "tax",
                "tip",
                "total",
                "cash",
                "change",
                "currency",
            }.issubset(transaction_fields)
        )


class HybridAnalyzeRouteTests(unittest.TestCase):
    def test_registered_http_route_merges_ocr_fallback(self) -> None:
        result = AnalyzeResult(
            content=(
                "HARGA JUAL\nTOTAL\nTUNAI\nKEMBALI\nANDA HEMAT\n"
                "77,400\n75,400\n100,500\n25,100\n2,000\n"
                "DPP= 70,364 PPN= 7,036"
            ),
            pages=[
                SimpleNamespace(
                    lines=[
                        SimpleNamespace(
                            content=text,
                            polygon=[
                                SimpleNamespace(x=x1, y=y),
                                SimpleNamespace(x=x1 + 1, y=y),
                                SimpleNamespace(x=x1 + 1, y=y + 0.1),
                                SimpleNamespace(x=x1, y=y + 0.1),
                            ],
                        )
                        for text, x1, y in (
                            ("HARGA JUAL", 0, 0.1),
                            ("TOTAL", 0, 0.3),
                            ("TUNAI", 0, 0.5),
                            ("KEMBALI", 0, 0.7),
                            ("ANDA HEMAT", 0, 0.9),
                            ("77,400", 2, 0.1),
                            ("75,400", 2, 0.3),
                            ("100,500", 2, 0.5),
                            ("25,100", 2, 0.7),
                            ("2,000", 2, 0.9),
                            ("DPP= 70,364 PPN= 7,036", 0, 1.1),
                        )
                    ]
                )
            ],
            documents=[
                AnalyzedDocument(
                    fields={
                        "Subtotal": DocumentField(
                            value_currency=CurrencyValue(
                                amount=77_400,
                                currency_code="IDR",
                            )
                        ),
                        "TotalTax": DocumentField(
                            value_currency=CurrencyValue(
                                amount=7_036,
                                currency_code="IDR",
                            )
                        ),
                        "Total": DocumentField(
                            value_currency=CurrencyValue(
                                amount=75_400,
                                currency_code="IDR",
                            )
                        ),
                        "Items": DocumentField(
                            value_array=[
                                DocumentField(
                                    confidence=0.9,
                                    value_object={
                                        "Description": DocumentField(
                                            value_string="Azure item"
                                        ),
                                        "Quantity": DocumentField(
                                            value_number=1
                                        ),
                                    },
                                )
                            ]
                        ),
                    },
                )
            ],
        )

        class FakeDocumentIntelligenceService:
            calls = 0

            def analyze_document(self, document_content: bytes) -> AnalyzeResult:
                self.calls += 1
                if document_content != b"receipt":
                    raise AssertionError("Unexpected document bytes")
                return result

        service = FakeDocumentIntelligenceService()
        print("Mocked AnalyzeResult.content repr:", repr(result.content))
        for line_index, line in enumerate(result.pages[0].lines):
            print(f"Mocked OCR line {line_index}: {line.content!r}")
        analyze_routes = [
            route
            for route in documents_router.routes
            if getattr(route, "path", None) == "/documents/analyze"
            and "POST" in (getattr(route, "methods", None) or set())
        ]
        self.assertEqual(len(analyze_routes), 1)
        endpoint = analyze_routes[0].endpoint
        self.assertEqual(endpoint.__module__, "app.routes.documents")
        self.assertEqual(endpoint.__name__, "analyze_document")
        self.assertEqual(
            sum(
                getattr(route, "original_router", None) is documents_router
                for route in app.routes
            ),
            1,
        )

        with patch(
            "app.routes.documents.AzureDocumentIntelligenceService",
            return_value=service,
        ), TestClient(app) as client:
            response = client.post(
                "/documents/analyze",
                files={
                    "file": (
                        "receipt.pdf",
                        b"receipt",
                        "application/pdf",
                    )
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(service.calls, 1)
        self.assertEqual(
            response.json()["transaction"],
            {
                "date": None,
                "time": None,
                "subtotal": 77_400,
                "discount": 2_000,
                "tax": 7_036,
                "tip": None,
                "total": 75_400,
                "cash": 100_500,
                "change": 25_100,
                "currency": "IDR",
            },
        )


if __name__ == "__main__":
    unittest.main()

import logging
import json
import unittest
from datetime import date, time
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from PIL import Image
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
from app.services.document_input import ValidatedDocument
from app.services.extraction_validator import ReceiptExtractionValidator
from app.services.receipt_merger import ReceiptMerger
from app.services.receipt_normalizer import ReceiptNormalizer
from app.services.receipt_reconciler import ReceiptReconciler
from app.services.receipt_text_parser import ReceiptTextParser


def valid_jpeg_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (4, 4), color="white").save(output, format="JPEG")
    return output.getvalue()


def valid_pdf_bytes() -> bytes:
    return b"%PDF-1.4\n%%EOF"


def sari_roti_ocr_fixture() -> tuple[str, list[SimpleNamespace]]:
    fixture_path = Path(__file__).parent / "fixtures" / "sari_roti_ocr_layout.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    page = SimpleNamespace(
        lines=[
            SimpleNamespace(
                content=line["content"],
                polygon=[
                    SimpleNamespace(x=x, y=y)
                    for x, y in line["polygon"]
                ],
            )
            for line in fixture["pages"][0]["lines"]
        ]
    )
    return fixture["content"], [page]


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
    FIXTURE_DIRECTORY = Path(__file__).parent / "fixtures"

    @classmethod
    def _fixture_text(cls, name: str) -> str:
        return (cls.FIXTURE_DIRECTORY / name).read_text(encoding="utf-8")

    def test_parses_generic_description_quantity_unit_total_layout(self) -> None:
        parsed = ReceiptTextParser.parse(
            self._fixture_text("receipt_type_1_ocr.txt")
        )

        assert parsed.merchant.name is None
        assert len(parsed.items) == 3
        assert [
            (
                item.description_raw,
                item.quantity,
                item.unit_price,
                item.total_price,
            )
            for item in parsed.items
        ] == [
            ("INACO MANGGA 350ML", 3, 7200, 21600),
            ("LEMONILO MIE GRG 77G", 4, 7000, 28000),
            ("FRUIT TEA MRKISA 350", 2, 3900, 7800),
        ]
        assert parsed.transaction.subtotal == 57_400
        assert parsed.transaction.total == 57_400
        assert parsed.transaction.cash == 57_400
        assert parsed.transaction.tax == 5_218
        assert parsed.transaction.payment_method == "Tunai"

        validated = ReceiptExtractionValidator.validate(parsed)
        assert validated.requires_review is True
        assert "Merchant name was not detected" in validated.review_reasons

    def test_parses_quantity_first_items_and_marks_derived_prices(self) -> None:
        parsed = ReceiptTextParser.parse(
            self._fixture_text("receipt_type_2_ocr.txt")
        )

        assert parsed.merchant.name is None
        assert [item.total_price for item in parsed.items] == [
            11_500,
            14_000,
            10_500,
            7_500,
        ]
        assert [item.quantity for item in parsed.items] == [1, 1, 1, 1]
        assert [item.unit_price for item in parsed.items] == [
            11_500,
            14_000,
            10_500,
            7_500,
        ]
        assert all(
            item.source == "ocr_text_fallback_derived_unit_price"
            for item in parsed.items
        )
        assert parsed.transaction.subtotal == 43_500
        assert parsed.transaction.total == 43_500
        assert parsed.transaction.cash == 43_500
        assert parsed.transaction.payment_method == "Debit BCA"

        validated = ReceiptExtractionValidator.validate(parsed)
        assert validated.requires_review is True
        assert any(
            "Unit price for item 1 was derived" in reason
            for reason in validated.review_reasons
        )

    def test_conservative_item_pattern_requires_multiple_rows(self) -> None:
        parsed = ReceiptTextParser.parse(
            "Bread Butter Pudding 11,500\n"
            "Cream Brulle 14,000\n"
            "Subtotal 25,500\n"
            "Total 25,500"
        )
        single_candidate = ReceiptTextParser.parse(
            "Reference number 11,500\n"
            "Total 11,500"
        )

        assert len(parsed.items) == 2
        assert all(item.quantity is None for item in parsed.items)
        assert all(item.unit_price is None for item in parsed.items)
        assert [item.total_price for item in parsed.items] == [11_500, 14_000]
        assert single_candidate.items == []

    def test_item_fields_are_sorted_by_visual_coordinates(self) -> None:
        def line(text: str, x: float, y: float) -> SimpleNamespace:
            return SimpleNamespace(
                content=text,
                polygon=[
                    SimpleNamespace(x=x, y=y),
                    SimpleNamespace(x=x + 0.8, y=y),
                    SimpleNamespace(x=x + 0.8, y=y + 0.1),
                    SimpleNamespace(x=x, y=y + 0.1),
                ],
            )

        pages = [
            SimpleNamespace(
                lines=[
                    line("21,600", 3, 0.2),
                    line("3", 1, 0.2),
                    line("INACO MANGGA 350ML", 0, 0.2),
                    line("7200", 2, 0.2),
                    line("57,400", 2, 0.5),
                    line("HARGA JUAL", 0, 0.5),
                    line("TOTAL 57,400", 0, 0.7),
                ]
            )
        ]
        parsed = ReceiptTextParser.parse(
            "unstructured OCR order",
            pages=pages,
        )

        assert len(parsed.items) == 1
        assert parsed.items[0].description_raw == "INACO MANGGA 350ML"
        assert parsed.items[0].quantity == 3
        assert parsed.items[0].unit_price == 7200
        assert parsed.items[0].total_price == 21600
        assert parsed.transaction.subtotal == 57_400
        assert parsed.transaction.total == 57_400

    def test_parses_additional_date_and_time_formats(self) -> None:
        assert ReceiptTextParser.extract_datetime(
            "16.12.20-19:33"
        ) == (
            date(2020, 12, 16),
            time(19, 33),
        )
        assert ReceiptTextParser.extract_datetime(
            "10 May 19 16:32:47"
        ) == (
            date(2019, 5, 10),
            time(16, 32, 47),
        )

    def test_payment_method_recognition_is_limited_to_known_labels(self) -> None:
        assert (
            ReceiptTextParser.parse(
                "Tea 5,000\nDebit BCA 5,000"
            ).transaction.payment_method
            == "Debit BCA"
        )
        assert (
            ReceiptTextParser.parse(
                "Tea 5,000\nUnknown Terminal 5,000"
            ).transaction.payment_method
            is None
        )

    def test_derives_unit_price_without_rewriting_inconsistent_values(self) -> None:
        receipt = Receipt(
            merchant=Merchant(name="Known merchant"),
            transaction=Transaction(subtotal=12, total=12),
            items=[
                ReceiptItem(
                    description_raw="Item",
                    quantity=2,
                    unit_price=4,
                    total_price=10,
                )
            ],
        )

        validated = ReceiptExtractionValidator.validate(receipt)

        assert validated.items[0].unit_price == 4
        assert validated.items[0].total_price == 10
        assert validated.requires_review is True
        assert any(
            "are inconsistent" in reason
            for reason in validated.review_reasons
        )
        assert any(
            "Sum of item totals does not match" in reason
            for reason in validated.review_reasons
        )

    def test_derives_missing_azure_unit_price_and_marks_its_source(self) -> None:
        receipt = Receipt(
            merchant=Merchant(name="Known merchant"),
            transaction=Transaction(subtotal=100, total=100),
            items=[
                ReceiptItem(
                    description_raw="Item",
                    quantity=2,
                    unit_price=None,
                    total_price=100,
                )
            ],
        )

        validated = ReceiptExtractionValidator.validate(receipt)

        assert validated.items[0].unit_price == 50
        assert (
            validated.items[0].source
            == "azure_prebuilt_receipt_derived_unit_price"
        )
        assert validated.requires_review is True
        assert any(
            "Unit price for item 1 was derived" in reason
            for reason in validated.review_reasons
        )

    def test_normalizes_optional_azure_payment_method(self) -> None:
        result = AnalyzeResult(
            documents=[
                AnalyzedDocument(
                    fields={
                        "PaymentMethod": DocumentField(
                            value_string="Credit Card"
                        )
                    }
                )
            ]
        )

        normalized = ReceiptNormalizer().normalize(result)

        assert normalized.transaction.payment_method == "Credit Card"

    def test_normalizes_optional_azure_cash_and_change_fields(self) -> None:
        result = AnalyzeResult(
            documents=[
                AnalyzedDocument(
                    fields={
                        "Cash": DocumentField(
                            value_currency=CurrencyValue(
                                amount=5_000,
                                currency_code="IDR",
                            )
                        ),
                        "ChangeDue": DocumentField(
                            value_currency=CurrencyValue(
                                amount=500,
                                currency_code="IDR",
                            )
                        ),
                    }
                )
            ]
        )

        normalized = ReceiptNormalizer().normalize(result)

        assert normalized.transaction.cash == 5_000
        assert normalized.transaction.change == 500
        assert normalized.transaction.currency == "IDR"

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
            "KEMBALIAN : 25,100",
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

    def test_total_item_row_does_not_confuse_item_count_with_total(self) -> None:
        receipt = ReceiptTextParser.parse(
            "SARI ROTI SM CK 1 4,500 4,500\n"
            "Total Item 1 4,500\n"
            "Tunai 5,000\n"
            "Kembalian 500\n"
            "PPN (409)"
        )

        self.assertEqual(len(receipt.items), 1)
        self.assertEqual(
            (
                receipt.items[0].quantity,
                receipt.items[0].unit_price,
                receipt.items[0].total_price,
            ),
            (1, 4_500, 4_500),
        )
        self.assertEqual(receipt.transaction.total, 4_500)
        self.assertEqual(receipt.transaction.cash, 5_000)
        self.assertEqual(receipt.transaction.change, 500)
        self.assertEqual(receipt.transaction.tax, 409)

    def test_sari_roti_azure_line_geometry_associates_split_summary_values(
        self,
    ) -> None:
        content, pages = sari_roti_ocr_fixture()
        receipt = ReceiptTextParser.parse(content, pages=pages)

        self.assertEqual(len(receipt.items), 1)
        self.assertEqual(
            (
                receipt.items[0].quantity,
                receipt.items[0].unit_price,
                receipt.items[0].total_price,
            ),
            (1, 4_500, 4_500),
        )
        self.assertEqual(receipt.transaction.total, 4_500)
        self.assertEqual(receipt.transaction.cash, 5_000)
        self.assertEqual(receipt.transaction.change, 500)
        self.assertEqual(receipt.transaction.tax, 409)

    def test_adjacent_label_fallback_does_not_reuse_tax_as_change(self) -> None:
        content = "KEMBALIAN\nPPN\n409"

        self.assertIsNone(
            ReceiptTextParser.extract_summary_value(content, "change")
        )
        self.assertEqual(
            ReceiptTextParser.extract_summary_value(content, "tax"),
            409,
        )

    def test_summary_labels_select_the_amount_for_their_semantics(self) -> None:
        for label in (
            "TOTAL ITEM",
            "TOTAL ITEMS",
            "JUMLAH ITEM",
            "ITEM COUNT",
        ):
            with self.subTest(label=label):
                self.assertEqual(
                    ReceiptTextParser.extract_summary_value(
                        [f"{label} 3 57,400"],
                        "total",
                    ),
                    57_400,
                )
                self.assertIsNone(
                    ReceiptTextParser.extract_summary_value(
                        [f"{label} 3"],
                        "total",
                    )
                )
        self.assertEqual(
            ReceiptTextParser.extract_summary_value(
                ["TOTAL 57,400"],
                "total",
            ),
            57_400,
        )
        for label in ("KEMBALI", "KEMBALIAN", "CHANGE", "CHANGE DUE"):
            with self.subTest(label=label):
                self.assertEqual(
                    ReceiptTextParser.extract_summary_value(
                        [f"{label} 500"],
                        "change",
                    ),
                    500,
                )

    def test_generic_indonesian_summary_aliases(self) -> None:
        for field_name, lines, expected in (
            (
                "subtotal",
                ("SUBTOTAL 4,500", "SUB TOTAL 4,500", "HARGA JUAL 4,500"),
                4_500,
            ),
            (
                "discount",
                ("DISKON 500", "DISCOUNT 500", "ANDA HEMAT 500"),
                500,
            ),
            (
                "cash",
                ("TUNAI 5,000", "CASH 5,000", "BAYAR 5,000", "UANG TUNAI 5,000"),
                5_000,
            ),
            (
                "tax",
                ("PPN (409)", "PAJAK (409)", "TAX (409)"),
                409,
            ),
            (
                "total",
                ("TOTAL 4,500", "GRAND TOTAL 4,500", "TOTAL BAYAR 4,500", "TOTAL PAYMENT 4,500"),
                4_500,
            ),
        ):
            for line in lines:
                with self.subTest(field=field_name, line=line):
                    self.assertEqual(
                        ReceiptTextParser.extract_summary_value(
                            [line],
                            field_name,
                        ),
                        expected,
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

    def test_complete_azure_items_are_not_overwritten(self) -> None:
        primary = Receipt(
            items=[
                ReceiptItem(
                    description_raw="Azure item",
                    quantity=1,
                    unit_price=10,
                    total_price=10,
                    source="azure_prebuilt_receipt",
                )
            ]
        )
        fallback = Receipt(
            items=[
                ReceiptItem(
                    description_raw="Azure item",
                    quantity=2,
                    unit_price=20,
                    total_price=40,
                    source="ocr_text_fallback",
                )
            ],
            extraction_method="ocr_text_fallback",
        )

        merged = ReceiptMerger.merge(primary, fallback)

        self.assertEqual(len(merged.items), 1)
        self.assertEqual(merged.items[0].quantity, 1)
        self.assertEqual(merged.items[0].unit_price, 10)
        self.assertEqual(merged.items[0].total_price, 10)
        self.assertEqual(merged.items[0].source, "azure_prebuilt_receipt")

    def test_fallback_fills_missing_fields_on_matching_azure_item(self) -> None:
        primary = Receipt(
            items=[
                ReceiptItem(
                    description_raw="Azure item",
                    quantity=1,
                    unit_price=None,
                    total_price=10,
                    source="azure_prebuilt_receipt",
                )
            ]
        )
        fallback = Receipt(
            items=[
                ReceiptItem(
                    description_raw="Azure item",
                    quantity=1,
                    unit_price=10,
                    total_price=10,
                    source="ocr_text_fallback",
                )
            ],
            extraction_method="ocr_text_fallback",
        )

        merged = ReceiptMerger.merge(primary, fallback)

        self.assertEqual(merged.items[0].unit_price, 10)
        self.assertEqual(
            merged.items[0].source,
            "azure_prebuilt_receipt+ocr_text_fallback",
        )


class ReceiptReconcilerTests(unittest.TestCase):
    def test_structured_total_needs_two_agreeing_signals_to_be_replaced(
        self,
    ) -> None:
        receipt = Receipt(
            transaction=Transaction(subtotal=4_500, total=1),
        )

        reasons = ReceiptReconciler.reconcile(
            receipt,
            structured_total=1,
        )

        self.assertEqual(receipt.transaction.total, 1)
        self.assertEqual(reasons, [])

    def test_reconciles_suspicious_total_from_independent_receipt_values(
        self,
    ) -> None:
        receipt = Receipt(
            transaction=Transaction(
                subtotal=4_500,
                tax=409,
                total=1,
                cash=5_000,
                change=500,
            ),
            items=[
                ReceiptItem(
                    description_raw="SARI ROTI SW CK",
                    quantity=1,
                    unit_price=4_500,
                    total_price=4_500,
                )
            ],
        )
        ocr_receipt = Receipt(
            transaction=Transaction(
                total=4_500,
                cash=5_000,
                change=500,
            ),
        )

        reasons = ReceiptReconciler.reconcile(
            receipt,
            structured_total=1,
            ocr_receipt=ocr_receipt,
        )

        self.assertEqual(receipt.transaction.total, 4_500)
        self.assertEqual(
            reasons,
            [ReceiptReconciler.TOTAL_RECONCILIATION_REASON],
        )

    def test_reconciles_structured_change_only_with_ocr_and_amount_evidence(
        self,
    ) -> None:
        receipt = Receipt(
            transaction=Transaction(
                subtotal=4_500,
                tax=409,
                total=4_500,
                cash=5_000,
                change=409,
            ),
            items=[
                ReceiptItem(
                    description_raw="SARI ROTI SW CK",
                    quantity=1,
                    unit_price=4_500,
                    total_price=4_500,
                )
            ],
        )
        ocr_receipt = Receipt(
            transaction=Transaction(
                total=4_500,
                cash=5_000,
                change=500,
            ),
        )

        reasons = ReceiptReconciler.reconcile(
            receipt,
            structured_total=4_500,
            structured_change=409,
            ocr_receipt=ocr_receipt,
        )

        self.assertEqual(receipt.transaction.change, 500)
        self.assertIn(
            ReceiptReconciler.CHANGE_RECONCILIATION_REASON,
            reasons,
        )

    def test_change_is_derived_only_when_cash_covers_total(self) -> None:
        covered = Receipt(
            transaction=Transaction(total=4_500, cash=5_000),
        )
        underpaid = Receipt(
            transaction=Transaction(total=4_500, cash=4_000),
        )

        ReceiptReconciler.reconcile(
            covered,
            structured_total=4_500,
        )
        ReceiptReconciler.reconcile(
            underpaid,
            structured_total=4_500,
        )

        self.assertEqual(covered.transaction.change, 500)
        self.assertIsNone(underpaid.transaction.change)


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
                "payment_method",
            }.issubset(transaction_fields)
        )


class HybridAnalyzeRouteTests(unittest.TestCase):
    def test_debug_analysis_logs_and_returns_ocr_geometry(self) -> None:
        content = "Tea 5,000"
        line = SimpleNamespace(
            content="Tea 5,000",
            polygon=[
                SimpleNamespace(x=0.1, y=0.2),
                SimpleNamespace(x=0.8, y=0.2),
                SimpleNamespace(x=0.8, y=0.3),
                SimpleNamespace(x=0.1, y=0.3),
            ],
        )
        result = AnalyzeResult(
            content=content,
            pages=[SimpleNamespace(lines=[line])],
            documents=[
                AnalyzedDocument(
                    fields={
                        "Items": DocumentField(
                            value_array=[
                                DocumentField(
                                    value_object={
                                        "Description": DocumentField(
                                            value_string="Tea"
                                        ),
                                        "TotalPrice": DocumentField(
                                            value_number=5000
                                        ),
                                    }
                                )
                            ]
                        )
                    }
                )
            ],
        )

        class FakeDocumentIntelligenceService:
            def analyze_document(
                self,
                document: ValidatedDocument,
            ) -> AnalyzeResult:
                if document.analysis_content != valid_jpeg_bytes():
                    raise AssertionError("Unexpected document bytes")
                return result

        with patch(
            "app.routes.documents.AzureDocumentIntelligenceService",
            FakeDocumentIntelligenceService,
        ), TestClient(app) as client, self.assertLogs(
            "app.routes.documents",
            level="INFO",
        ) as logs:
            response = client.post(
                "/documents/debug-analysis",
                files={
                    "file": (
                        "receipt.jpg",
                        valid_jpeg_bytes(),
                        "image/jpeg",
                    )
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["documents"][0]["field_names"], ["Items"])
        self.assertEqual(len(body["documents"][0]["items"]["value"]), 1)
        self.assertEqual(
            body["pages"][0]["lines"][0],
            {
                "index": 0,
                "text": "Tea 5,000",
                "polygon": [
                    {"x": 0.1, "y": 0.2},
                    {"x": 0.8, "y": 0.2},
                    {"x": 0.8, "y": 0.3},
                    {"x": 0.1, "y": 0.3},
                ],
            },
        )
        self.assertTrue(
            any(repr(content) in record for record in logs.output)
        )
        self.assertTrue(
            any("structured field names" in record for record in logs.output)
        )
        self.assertTrue(
            any("returned items" in record for record in logs.output)
        )
        self.assertTrue(
            any("OCR page 0 line 0" in record for record in logs.output)
        )

    def test_berkaa_structured_items_survive_generic_ocr_fallback(self) -> None:
        content = (
            Path(__file__).parent / "fixtures" / "berkaa_shop_ocr.txt"
        ).read_text(encoding="utf-8")
        item_values = [
            ("Nasi Ayam Geprek", 1, 12000),
            ("Nasi Ayam Kremes", 1, 15000),
            ("Nasi Goreng Spesial", 1, 20000),
        ]
        result = AnalyzeResult(
            content=content,
            pages=[
                SimpleNamespace(
                    lines=[
                        SimpleNamespace(content=line)
                        for line in content.splitlines()
                    ]
                )
            ],
            documents=[
                AnalyzedDocument(
                    confidence=0.98,
                    fields={
                        "MerchantName": DocumentField(
                            value_string="Berkaa Shop"
                        ),
                        "TransactionDate": DocumentField(
                            value_date=date(2022, 4, 14)
                        ),
                        "TransactionTime": DocumentField(
                            value_time=time(14, 24, 34)
                        ),
                        "Subtotal": DocumentField(
                            value_currency=CurrencyValue(
                                amount=47000,
                                currency_code="IDR",
                            )
                        ),
                        "Total": DocumentField(
                            value_currency=CurrencyValue(
                                amount=47000,
                                currency_code="IDR",
                            )
                        ),
                        "Items": DocumentField(
                            value_array=[
                                DocumentField(
                                    confidence=0.98,
                                    value_object={
                                        "Description": DocumentField(
                                            value_string=description
                                        ),
                                        "Quantity": DocumentField(
                                            value_number=quantity
                                        ),
                                        "Price": DocumentField(
                                            value_number=amount
                                        ),
                                        "TotalPrice": DocumentField(
                                            value_number=amount
                                        ),
                                    },
                                )
                                for description, quantity, amount
                                in item_values
                            ]
                        ),
                    },
                )
            ],
        )

        class FakeDocumentIntelligenceService:
            def analyze_document(
                self,
                document: ValidatedDocument,
            ) -> AnalyzeResult:
                if document.analysis_content != valid_jpeg_bytes():
                    raise AssertionError("Unexpected document bytes")
                return result

        with patch(
            "app.services.receipt_extraction.AzureDocumentIntelligenceService",
            FakeDocumentIntelligenceService,
        ), TestClient(app) as client:
            response = client.post(
                "/documents/analyze",
                files={
                    "file": (
                        "receipt.jpg",
                        valid_jpeg_bytes(),
                        "image/jpeg",
                    )
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["merchant"]["name"], "Berkaa Shop")
        self.assertEqual(body["transaction"]["date"], "2022-04-14")
        self.assertEqual(body["transaction"]["time"], "14:24:34")
        self.assertEqual(body["transaction"]["subtotal"], 47000)
        self.assertEqual(body["transaction"]["total"], 47000)
        self.assertEqual(body["transaction"]["cash"], 47000)
        self.assertEqual(body["transaction"]["change"], 0)
        self.assertEqual(body["transaction"]["payment_method"], "Cash")
        self.assertEqual(
            [item["description_raw"] for item in body["items"]],
            [value[0] for value in item_values],
        )
        self.assertFalse(body["requires_review"])

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

            def analyze_document(
                self,
                document: ValidatedDocument,
            ) -> AnalyzeResult:
                self.calls += 1
                if document.analysis_content != valid_pdf_bytes():
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
            "app.services.receipt_extraction.AzureDocumentIntelligenceService",
            return_value=service,
        ), TestClient(app) as client:
            response = client.post(
                "/documents/analyze",
                files={
                    "file": (
                        "receipt.pdf",
                        valid_pdf_bytes(),
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
                "payment_method": "Tunai",
            },
        )


if __name__ == "__main__":
    unittest.main()

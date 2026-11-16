import re
from datetime import datetime

from app.schemas.receipt import (
    Merchant,
    Receipt,
    ReceiptItem,
    Transaction,
)


class ReceiptTextParser:
    ITEM_PATTERN = re.compile(
        r"^(?P<description>.+?)\s+"
        r"(?P<quantity>\d+(?:[.,]\d+)?)\s+"
        r"(?P<unit_price>\d[\d.,]*)\s+"
        r"(?P<total_price>\(?\d[\d.,]*\)?)$"
    )

    @staticmethod
    def parse_number(value: str | None) -> float | None:
        if value is None:
            return None

        cleaned = value.strip()

        if not cleaned:
            return None

        negative = (
            cleaned.startswith("(")
            and cleaned.endswith(")")
        )

        cleaned = re.sub(
            r"(?i)\b(?:rp|idr)\b",
            "",
            cleaned,
        )

        cleaned = cleaned.replace("(", "").replace(")", "")
        cleaned = cleaned.replace(" ", "")

        if not cleaned:
            return None

        # Receipt values are expected to be monetary whole numbers.
        # Both 12.000 and 12,000 are interpreted as 12000.
        if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", cleaned):
            cleaned = cleaned.replace(".", "").replace(",", "")

        elif "," in cleaned and "." not in cleaned:
            parts = cleaned.split(",")

            if len(parts[-1]) == 3:
                cleaned = cleaned.replace(",", "")
            else:
                cleaned = cleaned.replace(",", ".")

        elif "." in cleaned and "," not in cleaned:
            parts = cleaned.split(".")

            if len(parts[-1]) == 3:
                cleaned = cleaned.replace(".", "")

        elif "," in cleaned and "." in cleaned:
            last_comma = cleaned.rfind(",")
            last_dot = cleaned.rfind(".")

            if last_comma > last_dot:
                cleaned = cleaned.replace(".", "")
                cleaned = cleaned.replace(",", ".")
            else:
                cleaned = cleaned.replace(",", "")

        try:
            result = float(cleaned)
        except ValueError:
            return None

        return -result if negative else result


    @classmethod
    def parse_item_line(
        cls,
        line: str,
    ) -> ReceiptItem | None:
        normalized_line = " ".join(line.split())

        match = cls.ITEM_PATTERN.match(normalized_line)

        if not match:
            return None

        description = match.group("description").strip()

        quantity = cls.parse_number(
            match.group("quantity")
        )

        unit_price = cls.parse_number(
            match.group("unit_price")
        )

        total_price = cls.parse_number(
            match.group("total_price")
        )

        if not description:
            return None

        if quantity is None or unit_price is None:
            return None

        # Avoid interpreting summary rows as product items.
        excluded_descriptions = {
            "total",
            "subtotal",
            "sub total",
            "harga jual",
            "tunai",
            "cash",
            "kembali",
            "change",
            "diskon",
            "discount",
            "anda hemat",
            "dpp",
            "ppn",
            "tax",
        }

        if description.lower().strip(": ") in excluded_descriptions:
            return None

        return ReceiptItem(
            description_raw=description,
            description_normalized=None,
            quantity=quantity,
            unit_price=unit_price,
            total_price=total_price,
            confidence=None,
            source="ocr_text_fallback",
        )


    SUMMARY_PATTERNS = {
        "subtotal": [
            r"(?i)^\s*sub\s*total\s*:?\s*(?P<value>[\d.,]+)\s*$",
            r"(?i)^\s*harga\s+jual\s*:?\s*(?P<value>[\d.,]+)\s*$",
        ],
        "discount": [
            r"(?i)^\s*(?:diskon|discount|anda\s+hemat)"
            r"\s*:?\s*(?P<value>\(?[\d.,]+\)?)\s*$",
        ],
        "total": [
            r"(?i)^\s*total\s*:?\s*(?P<value>[\d.,]+)\s*$",
        ],
        "cash": [
            r"(?i)^\s*(?:tunai|cash|bayar(?:\s*\(cash\))?)"
            r"\s*:?\s*(?P<value>[\d.,]+)\s*$",
        ],
        "change": [
            r"(?i)^\s*(?:kembali|change)"
            r"\s*:?\s*(?P<value>[\d.,]+)\s*$",
        ],
        "tax": [
            r"(?i).*\b(?:ppn|tax)\s*[=:]\s*"
            r"(?P<value>[\d.,]+).*",
        ],
    }

    @classmethod
    def extract_summary_value(
        cls,
        lines: list[str],
        field_name: str,
    ) -> float | None:
        patterns = cls.SUMMARY_PATTERNS[field_name]

        for line in lines:
            normalized_line = " ".join(line.split())

            for pattern in patterns:
                match = re.match(pattern, normalized_line)

                if match:
                    value = cls.parse_number(
                        match.group("value")
                    )

                    if field_name == "discount" and value is not None:
                        return abs(value)

                    return value

        return None

    DATE_TIME_PATTERNS = [
        (
            re.compile(
                r"\b(?P<date>\d{2}\.\d{2}\.\d{2})"
                r"?P<time>\d{2}:\d{2}\b"
            ),
            "%d.%m.%y",
            "%H:%M",
        ),
        (
            re.compile(
                r"\b(?P<date>\d{4}-\d{2}-\d{2})"
                r"(?:\s+(?P<time>\d{2}:\d{2}(?::\d{2})?))?"
            ),
            "%Y-%m-%d",
            None,
        ),
    ]

    @classmethod
    def extract_datetime(cls, content: str):
        for pattern, date_format, fixed_time_format in (
            cls.DATE_TIME_PATTERNS
        ):
            match = pattern.search(content)

            if not match:
                continue

            parsed_date = datetime.strptime(
                match.group("date"),
                date_format,
            ).date()

            time_text = match.groupdict().get("time")
            parsed_time = None

            if time_text:
                time_format = (
                    fixed_time_format
                    or (
                        "%H:%M:%S"
                        if time_text.count(":") == 2
                        else "%H:%M"
                    )
                )

                parsed_time = datetime.strptime(
                    time_text,
                    time_format,
                ).time()

            return parsed_date, parsed_time

        return None, None

    @classmethod
    def parse(cls, content: str) -> Receipt:
        lines = [
            " ".join(line.split())
            for line in content.splitlines()
            if line.strip()
        ]

        items: list[ReceiptItem] = []

        for line in lines:
            item = cls.parse_item_line(line)

            if item:
                items.append(item)

        transaction_date, transaction_time = (
            cls.extract_datetime(content)
        )

        merchant_name = lines[0] if lines else None

        receipt = Receipt(
            merchant=Merchant(
                name=merchant_name,
            ),
            transaction=Transaction(
                date=transaction_date,
                time=transaction_time,
                subtotal=cls.extract_summary_value(
                    lines,
                    "subtotal",
                ),
                discount=cls.extract_summary_value(
                    lines,
                    "discount",
                ),
                tax=cls.extract_summary_value(
                    lines,
                    "tax",
                ),
                total=cls.extract_summary_value(
                    lines,
                    "total",
                ),
                cash=cls.extract_summary_value(
                    lines,
                    "cash",
                ),
                change=cls.extract_summary_value(
                    lines,
                    "change",
                ),
                currency="IDR",
            ),
            items=items,
            extraction_method="ocr_text_fallback",
            confidence=None,
        )

        return receipt
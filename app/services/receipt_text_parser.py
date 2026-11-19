import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

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

        cleaned = re.sub(r"(?i)^\s*(?:rp\.?|idr)\s*", "", cleaned)

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


    SUMMARY_LABELS = {
        "subtotal": (r"HARGA\s+JUAL", r"SUB\s*TOTAL"),
        "discount": (r"ANDA\s+HEMAT", r"DISKON", r"DISCOUNT"),
        "total": (r"TOTAL",),
        "cash": (r"BAYAR\s*\(\s*CASH\s*\)", r"TUNAI", r"CASH", r"BAYAR"),
        "change": (r"KEMBALI", r"CHANGE"),
        "tax": (r"PPN", r"TAX"),
    }

    SUMMARY_LABEL_PATTERN = re.compile(
        r"(?<!\w)(?P<label>"
        + "|".join(
            rf"(?P<{field}_{index}>{label})"
            for field, labels in SUMMARY_LABELS.items()
            for index, label in enumerate(labels)
        )
        + r")(?!\w)",
        re.IGNORECASE,
    )
    SUMMARY_NUMBER_PATTERN = re.compile(
        r"^\s*[:=]?\s*(?:(?:RP\.?|IDR)\s*)?"
        r"(?P<value>\(?\s*-?\d[\d.,]*\s*\)?|-?\d[\d.,]*)"
        r"(?![\w.,])",
        re.IGNORECASE,
    )
    NUMERIC_LINE_PATTERN = re.compile(
        r"^\s*(?:(?:RP\.?|IDR)\s*)?"
        r"(?P<value>\(?\s*-?\d[\d.,]*\s*\)?|-?\d[\d.,]*)\s*$",
        re.IGNORECASE,
    )

    SUMMARY_GROUP_FIELDS = {
        f"{field}_{index}": field
        for field, labels in SUMMARY_LABELS.items()
        for index, _ in enumerate(labels)
    }

    @staticmethod
    def normalize_content(content: str) -> tuple[str, str]:
        normalized = (
            content.replace("\r\n", "\n")
            .replace("\r", "\n")
            .replace("\u00a0", " ")
        )
        compact = re.sub(r"\s+", " ", normalized).strip()
        return normalized, compact

    @staticmethod
    def _attribute(value: Any, name: str) -> Any:
        if isinstance(value, Mapping):
            camel_name = name.split("_")[0] + "".join(
                part.title() for part in name.split("_")[1:]
            )
            return value.get(name, value.get(camel_name))
        return getattr(value, name, None)

    @classmethod
    def _line_bounds(
        cls,
        line: Any,
    ) -> tuple[float, float, float, float] | None:
        polygon = cls._attribute(line, "polygon")
        if not polygon:
            polygon = cls._attribute(line, "bounding_polygon")
        if not polygon:
            return None

        points: list[tuple[float, float]] = []
        if isinstance(polygon, Sequence) and not isinstance(polygon, (str, bytes)):
            if polygon and isinstance(polygon[0], (int, float)):
                points = [
                    (float(polygon[index]), float(polygon[index + 1]))
                    for index in range(0, len(polygon) - 1, 2)
                ]
            else:
                for point in polygon:
                    x = cls._attribute(point, "x")
                    y = cls._attribute(point, "y")
                    if isinstance(x, (int, float)) and isinstance(
                        y,
                        (int, float),
                    ):
                        points.append((float(x), float(y)))

        if not points:
            return None

        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        return min(xs), min(ys), max(xs), max(ys)

    @classmethod
    def _ocr_lines(
        cls,
        content: str,
        pages: Sequence[Any] | None,
    ) -> list[tuple[str, tuple[float, float, float, float] | None]]:
        page_lines: list[tuple[str, tuple[float, float, float, float] | None]] = []
        for page in pages or ():
            lines = cls._attribute(page, "lines") or ()
            for line in lines:
                line_content = cls._attribute(line, "content")
                if isinstance(line_content, str) and line_content.strip():
                    page_lines.append(
                        (line_content, cls._line_bounds(line))
                    )

        if page_lines:
            return page_lines

        normalized, _ = cls.normalize_content(content)
        return [
            (line.strip(), None)
            for line in normalized.split("\n")
            if line.strip()
        ]

    @classmethod
    def _labels_on_line(
        cls,
        line: str,
    ) -> list[tuple[str, re.Match[str]]]:
        labels: list[tuple[str, re.Match[str]]] = []
        for match in cls.SUMMARY_LABEL_PATTERN.finditer(line):
            field_name = next(
                (
                    field
                    for group_name, field in cls.SUMMARY_GROUP_FIELDS.items()
                    if match.group(group_name) is not None
                ),
                None,
            )
            if field_name is not None:
                labels.append((field_name, match))
        return labels

    @classmethod
    def _parse_number_after_label(cls, text: str) -> float | None:
        match = cls.SUMMARY_NUMBER_PATTERN.match(text)
        if match is None:
            return None
        return cls.parse_number(match.group("value"))

    @classmethod
    def _parse_numeric_line(cls, text: str) -> float | None:
        match = cls.NUMERIC_LINE_PATTERN.fullmatch(text)
        if match is None:
            return None
        return cls.parse_number(match.group("value"))

    @staticmethod
    def _discount_value(field_name: str, value: float | None) -> float | None:
        if field_name == "discount" and value is not None:
            return abs(value)
        return value

    @classmethod
    def _extract_summary_values(
        cls,
        content: str,
        pages: Sequence[Any] | None = None,
    ) -> dict[str, float | None]:
        lines = cls._ocr_lines(content, pages)
        values: dict[str, float | None] = {
            field: None for field in cls.SUMMARY_LABELS
        }
        label_locations: list[
            tuple[str, int, tuple[float, float, float, float] | None]
        ] = []
        line_labels: list[list[tuple[str, re.Match[str]]]] = []

        for line_index, (line, bounds) in enumerate(lines):
            labels = cls._labels_on_line(line)
            line_labels.append(labels)
            for label_index, (field_name, match) in enumerate(labels):
                label_locations.append((field_name, line_index, bounds))
                if values[field_name] is not None:
                    continue

                end = (
                    labels[label_index + 1][1].start()
                    if label_index + 1 < len(labels)
                    else len(line)
                )
                value = cls._parse_number_after_label(
                    line[match.end():end]
                )
                if value is not None:
                    values[field_name] = cls._discount_value(field_name, value)

        used_numeric_lines: set[int] = set()
        for field_name, _, label_bounds in label_locations:
            if values[field_name] is not None or label_bounds is None:
                continue

            lx1, ly1, lx2, ly2 = label_bounds
            label_height = max(ly2 - ly1, 0.0)
            candidates: list[tuple[float, float, int, float]] = []
            for numeric_index, (line, numeric_bounds) in enumerate(lines):
                if numeric_index in used_numeric_lines or numeric_bounds is None:
                    continue
                if line_labels[numeric_index]:
                    continue
                numeric_value = cls._parse_numeric_line(line)
                if numeric_value is None:
                    continue

                nx1, ny1, nx2, ny2 = numeric_bounds
                if nx1 < lx2:
                    continue
                numeric_height = max(ny2 - ny1, 0.0)
                vertical_tolerance = (
                    max(label_height, numeric_height) * 0.75 + 0.03
                )
                label_center_y = (ly1 + ly2) / 2
                numeric_center_y = (ny1 + ny2) / 2
                vertical_distance = abs(label_center_y - numeric_center_y)
                if vertical_distance <= vertical_tolerance:
                    candidates.append(
                        (
                            nx1 - lx2,
                            vertical_distance,
                            numeric_index,
                            numeric_value,
                        )
                    )

            if candidates:
                _, _, numeric_index, value = min(candidates)
                used_numeric_lines.add(numeric_index)
                values[field_name] = cls._discount_value(field_name, value)

        for location_index, (field_name, line_index, _) in enumerate(
            label_locations
        ):
            if values[field_name] is not None:
                continue
            earlier_unresolved_label = any(
                values[previous_field] is None
                for previous_field, _, _ in label_locations[:location_index]
            )
            if earlier_unresolved_label:
                continue
            next_index = line_index + 1
            if next_index >= len(lines) or line_labels[next_index]:
                continue
            value = cls._parse_numeric_line(lines[next_index][0])
            if value is not None and next_index not in used_numeric_lines:
                used_numeric_lines.add(next_index)
                values[field_name] = cls._discount_value(field_name, value)

        return values

    @classmethod
    def extract_summary_value(
        cls,
        content: str | list[str],
        field_name: str,
        pages: Sequence[Any] | None = None,
    ) -> float | None:
        text = "\n".join(content) if isinstance(content, list) else content
        return cls._extract_summary_values(text, pages).get(field_name)

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
    def parse(
        cls,
        content: str,
        pages: Sequence[Any] | None = None,
    ) -> Receipt:
        normalized_content, _ = cls.normalize_content(content)
        summary_values = cls._extract_summary_values(
            normalized_content,
            pages,
        )
        lines = [
            " ".join(line.split())
            for line in normalized_content.splitlines()
            if line.strip()
        ]

        items: list[ReceiptItem] = []

        for line in lines:
            item = cls.parse_item_line(line)

            if item:
                items.append(item)

        transaction_date, transaction_time = (
            cls.extract_datetime(normalized_content)
        )

        merchant_name = lines[0] if lines else None

        receipt = Receipt(
            merchant=Merchant(
                name=merchant_name,
            ),
            transaction=Transaction(
                date=transaction_date,
                time=transaction_time,
                subtotal=summary_values["subtotal"],
                discount=summary_values["discount"],
                tax=summary_values["tax"],
                total=summary_values["total"],
                cash=summary_values["cash"],
                change=summary_values["change"],
                currency="IDR",
            ),
            items=items,
            extraction_method="ocr_text_fallback",
            confidence=None,
        )

        return receipt
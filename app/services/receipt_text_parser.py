import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any

from app.schemas.receipt import (
    Merchant,
    Receipt,
    ReceiptItem,
    Transaction,
)

_PolygonBounds = tuple[float, float, float, float]


@dataclass(frozen=True)
class _SummaryValueSource:
    field_name: str
    line_index: int
    span: tuple[int, int]
    polygon: _PolygonBounds | None
    method: str

    @property
    def token_key(self) -> tuple[int, int, int]:
        return (self.line_index, *self.span)


@dataclass(frozen=True)
class _VisualNumericCandidate:
    line_index: int
    value: float
    text: str
    bounds: _PolygonBounds
    span: tuple[int, int]
    vertical_distance: float
    horizontal_gap: float


class ReceiptTextParser:
    ITEM_PATTERN = re.compile(
        r"^(?P<description>.+?)\s+"
        r"(?P<quantity>\d+(?:[.,]\d+)?)\s+"
        r"(?P<unit_price>\d[\d.,]*)\s+"
        r"(?P<total_price>\(?\d[\d.,]*\)?)$"
    )
    QUANTITY_FIRST_ITEM_PATTERN = re.compile(
        r"^(?P<quantity>\d+(?:[.,]\d+)?)\s+"
        r"(?P<description>.+?)\s+"
        r"(?P<total_price>\(?\d[\d.,]*\)?)$"
    )
    CONSERVATIVE_ITEM_PATTERN = re.compile(
        r"^(?P<description>.+?)\s+"
        r"(?P<total_price>\(?\d[\d.,]*\)?)$"
    )
    PAYMENT_METHOD_PATTERN = re.compile(
        r"^(?:DEBIT(?:\s+[A-Z0-9][A-Z0-9/&-]*)*|"
        r"CREDIT\s+CARD|CASH|TUNAI)$",
        re.IGNORECASE,
    )
    TRAILING_AMOUNT_PATTERN = re.compile(
        r"\s*[:=]?\s*(?:(?:RP\.?|IDR)\s*)?"
        r"\(?-?\d[\d.,]*\)?\s*$",
        re.IGNORECASE,
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
        *,
        allow_conservative: bool = False,
    ) -> ReceiptItem | None:
        normalized_line = " ".join(line.split())

        match = cls.ITEM_PATTERN.match(normalized_line)
        if match is not None:
            description = match.group("description").strip()
            quantity = cls.parse_number(match.group("quantity"))
            unit_price = cls.parse_number(match.group("unit_price"))
            total_price = cls.parse_number(match.group("total_price"))
            if (
                description
                and quantity is not None
                and unit_price is not None
                and not cls._is_excluded_item_description(description)
            ):
                return ReceiptItem(
                    description_raw=description,
                    quantity=quantity,
                    unit_price=unit_price,
                    total_price=total_price,
                    confidence=None,
                    source="ocr_text_fallback",
                )

        match = cls.QUANTITY_FIRST_ITEM_PATTERN.match(normalized_line)
        if match is not None:
            description = match.group("description").strip()
            quantity = cls.parse_number(match.group("quantity"))
            total_price = cls.parse_number(match.group("total_price"))
            if (
                description
                and quantity is not None
                and total_price is not None
                and not cls._is_excluded_item_description(description)
            ):
                unit_price = (
                    total_price / quantity if quantity > 0 else None
                )
                source = (
                    "ocr_text_fallback_derived_unit_price"
                    if unit_price is not None
                    else "ocr_text_fallback"
                )
                return ReceiptItem(
                    description_raw=description,
                    quantity=quantity,
                    unit_price=unit_price,
                    total_price=total_price,
                    confidence=None,
                    source=source,
                )

        if not allow_conservative:
            return None

        match = cls.CONSERVATIVE_ITEM_PATTERN.match(normalized_line)
        if match is None:
            return None

        description = match.group("description").strip()
        total_price = cls.parse_number(match.group("total_price"))
        if (
            not description
            or total_price is None
            or not re.search(r"[A-Za-z]", description)
            or cls._is_excluded_item_description(description)
        ):
            return None

        return ReceiptItem(
            description_raw=description,
            quantity=None,
            unit_price=None,
            total_price=total_price,
            confidence=None,
            source="ocr_text_fallback_pattern_c",
        )

    @classmethod
    def _is_excluded_item_description(cls, description: str) -> bool:
        normalized = re.sub(r"[\s:]+", " ", description).strip().casefold()
        if normalized in {"x", "×", "rp", "idr"}:
            return True
        excluded_prefixes = (
            "total",
            "subtotal",
            "sub total",
            "harga jual",
            "tunai",
            "cash",
            "payment",
            "bayar",
            "debit",
            "credit",
            "kembali",
            "change",
            "diskon",
            "discount",
            "anda hemat",
            "dpp",
            "ppn",
            "tax",
        )
        return any(
            normalized == prefix or normalized.startswith(prefix + " ")
            for prefix in excluded_prefixes
        )


    SUMMARY_LABELS = {
        "subtotal": (r"HARGA\s+JUAL", r"SUB\s*TOTAL"),
        "discount": (r"ANDA\s+HEMAT", r"DISKON", r"DISCOUNT"),
        "item_count": (
            r"TOTAL\s+ITEMS?",
            r"JUMLAH\s+ITEMS?",
            r"ITEM\s+COUNT",
        ),
        "total": (
            r"GRAND\s+TOTAL",
            r"TOTAL\s+BAYAR",
            r"TOTAL\s+PAYMENT",
            r"TOTAL(?!\s+ITEMS?\b)",
        ),
        "cash": (
            r"UANG\s+TUNAI",
            r"BAYAR\s*\(\s*CASH\s*\)",
            r"TUNAI",
            r"CASH",
            r"PAYMENT",
            r"BAYAR",
        ),
        "change": (
            r"CHANGE\s+DUE",
            r"KEMBALIAN",
            r"KEMBALI",
            r"CHANGE",
        ),
        "tax": (r"PPN", r"PAJAK", r"TAX"),
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
    SUMMARY_CANDIDATE_PATTERN = re.compile(
        r"(?<![\w.,])(?P<value>\(?\s*-?\d[\d.,]*\s*\)?)(?![\w.,])",
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
    def _item_lines(
        cls,
        content: str,
        pages: Sequence[Any] | None,
    ) -> list[str]:
        page_rows: list[str] = []
        for page in pages or ():
            segments: list[
                tuple[str, tuple[float, float, float, float] | None]
            ] = []
            for line in cls._attribute(page, "lines") or ():
                line_content = cls._attribute(line, "content")
                if isinstance(line_content, str) and line_content.strip():
                    segments.append(
                        (line_content.strip(), cls._line_bounds(line))
                    )

            measured = [
                (text, bounds)
                for text, bounds in segments
                if bounds is not None
            ]
            unmeasured = [
                text for text, bounds in segments if bounds is None
            ]
            rows: list[
                list[tuple[str, tuple[float, float, float, float]]]
            ] = []
            for text, bounds in sorted(
                measured,
                key=lambda segment: (
                    (segment[1][1] + segment[1][3]) / 2,
                    segment[1][0],
                ),
            ):
                center_y = (bounds[1] + bounds[3]) / 2
                height = max(bounds[3] - bounds[1], 0.0)
                matching_row: list[
                    tuple[str, tuple[float, float, float, float]]
                ] | None = None
                for row in rows:
                    row_bounds = [item_bounds for _, item_bounds in row]
                    row_center = sum(
                        (item_bounds[1] + item_bounds[3]) / 2
                        for item_bounds in row_bounds
                    ) / len(row_bounds)
                    row_height = max(
                        item_bounds[3] - item_bounds[1]
                        for item_bounds in row_bounds
                    )
                    tolerance = max(height, row_height) * 0.75 + 0.03
                    if abs(center_y - row_center) <= tolerance:
                        matching_row = row
                        break
                if matching_row is None:
                    rows.append([(text, bounds)])
                else:
                    matching_row.append((text, bounds))

            rows.sort(
                key=lambda row: min(bounds[1] for _, bounds in row)
            )
            for row in rows:
                page_rows.append(
                    " ".join(
                        text
                        for text, _ in sorted(
                            row,
                            key=lambda segment: segment[1][0],
                        )
                    )
                )
            page_rows.extend(unmeasured)

        if page_rows:
            return page_rows

        normalized, _ = cls.normalize_content(content)
        return [
            " ".join(line.split())
            for line in normalized.splitlines()
            if line.strip()
        ]

    @classmethod
    def _payment_method(
        cls,
        content: str,
        pages: Sequence[Any] | None,
    ) -> str | None:
        for line, _ in cls._ocr_lines(content, pages):
            candidate = cls.TRAILING_AMOUNT_PATTERN.sub("", line).strip()
            candidate = re.sub(
                r"(?i)^PAYMENT(?:\s+METHOD)?\s*[:=]?\s*",
                "",
                candidate,
            ).strip()
            if re.fullmatch(
                r"BAYAR\s*\(\s*CASH\s*\)",
                candidate,
                re.IGNORECASE,
            ):
                return "Cash"
            if cls.PAYMENT_METHOD_PATTERN.fullmatch(candidate):
                if candidate.casefold() == "cash":
                    return "Cash"
                if candidate.casefold() == "tunai":
                    return "Tunai"
                if candidate.casefold() == "credit card":
                    return "Credit Card"
                if candidate.casefold().startswith("debit"):
                    return "Debit" + candidate[5:]
        return None

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
    def _summary_value(field_name: str, value: float | None) -> float | None:
        if field_name in {"discount", "tax"} and value is not None:
            return abs(value)
        return value

    @classmethod
    def _numeric_tokens(
        cls,
        text: str,
        pattern: re.Pattern[str],
    ) -> list[tuple[float, tuple[int, int], str]]:
        tokens: list[tuple[float, tuple[int, int], str]] = []
        for match in pattern.finditer(text):
            value = cls.parse_number(match.group("value"))
            if value is not None:
                tokens.append(
                    (
                        value,
                        match.span("value"),
                        match.group("value"),
                    )
                )
        return tokens

    @staticmethod
    def _line_center_and_height(
        bounds: _PolygonBounds,
    ) -> tuple[float, float]:
        _, y1, _, y2 = bounds
        return (y1 + y2) / 2, max(y2 - y1, 0.0)

    @classmethod
    def _is_monetary_formatted(cls, text: str) -> bool:
        return bool(
            re.search(r"(?i)\b(?:RP\.?|IDR)\s*\d", text)
            or re.search(r"\d[.,]\d{3}(?:[.,]\d{3})*(?!\d)", text)
        )

    @classmethod
    def _visual_row_candidates(
        cls,
        lines: list[tuple[str, _PolygonBounds | None]],
        line_labels: list[list[tuple[str, re.Match[str]]]],
        label_locations: list[
            tuple[str, int, _PolygonBounds | None]
        ],
        label_location_index: int,
        values: dict[str, float | None],
        used_numeric_lines: set[int],
    ) -> list[_VisualNumericCandidate]:
        _, _, label_bounds = label_locations[label_location_index]
        if label_bounds is None:
            return []

        label_center, label_height = cls._line_center_and_height(
            label_bounds
        )
        candidates: list[_VisualNumericCandidate] = []
        for numeric_index, (line, numeric_bounds) in enumerate(lines):
            if (
                numeric_index in used_numeric_lines
                or numeric_bounds is None
                or line_labels[numeric_index]
            ):
                continue
            match = cls.NUMERIC_LINE_PATTERN.fullmatch(line)
            if match is None:
                continue
            value = cls.parse_number(match.group("value"))
            if value is None:
                continue

            numeric_x1 = numeric_bounds[0]
            numeric_center, numeric_height = (
                cls._line_center_and_height(numeric_bounds)
            )
            matching_labels: list[tuple[float, float, int]] = []
            for other_index, (
                other_field,
                _,
                other_bounds,
            ) in enumerate(label_locations):
                if other_bounds is None:
                    continue
                needs_value = values[other_field] is None or (
                    other_field == "item_count"
                    and values["total"] is None
                )
                if not needs_value:
                    continue

                horizontal_gap = numeric_x1 - other_bounds[2]
                if horizontal_gap < 0:
                    continue
                other_center, other_height = (
                    cls._line_center_and_height(other_bounds)
                )
                vertical_distance = abs(numeric_center - other_center)
                vertical_tolerance = max(
                    numeric_height,
                    other_height,
                ) * 0.75
                if vertical_distance <= vertical_tolerance:
                    matching_labels.append(
                        (vertical_distance, horizontal_gap, other_index)
                    )

            if not matching_labels:
                continue
            closest = min(
                (vertical_distance, horizontal_gap)
                for vertical_distance, horizontal_gap, _ in matching_labels
            )
            owners = [
                other_index
                for vertical_distance, horizontal_gap, other_index
                in matching_labels
                if (vertical_distance, horizontal_gap) == closest
            ]
            if owners != [label_location_index]:
                continue

            candidates.append(
                _VisualNumericCandidate(
                    line_index=numeric_index,
                    value=value,
                    text=line,
                    bounds=numeric_bounds,
                    span=match.span("value"),
                    vertical_distance=abs(numeric_center - label_center),
                    horizontal_gap=numeric_x1 - label_bounds[2],
                )
            )

        return sorted(
            candidates,
            key=lambda candidate: (
                candidate.vertical_distance,
                candidate.horizontal_gap,
            ),
        )

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
        assigned_sources: dict[str, _SummaryValueSource] = {}
        used_numeric_lines: set[int] = set()
        item_count_totals: list[
            tuple[float, _SummaryValueSource]
        ] = []

        def assign(
            target_field: str,
            value: float,
            source: _SummaryValueSource,
        ) -> bool:
            if any(
                previous.token_key == source.token_key
                for previous in assigned_sources.values()
            ):
                return False
            assigned_sources[target_field] = source
            values[target_field] = cls._summary_value(
                target_field,
                value,
            )
            return True

        for line_index, (line, bounds) in enumerate(lines):
            labels = cls._labels_on_line(line)
            line_labels.append(labels)
            for label_index, (field_name, match) in enumerate(labels):
                label_locations.append((field_name, line_index, bounds))
                end = (
                    labels[label_index + 1][1].start()
                    if label_index + 1 < len(labels)
                    else len(line)
                )
                value_text = line[match.end():end]
                if field_name == "item_count":
                    if values[field_name] is not None:
                        continue
                    candidates = cls._numeric_tokens(
                        value_text,
                        cls.SUMMARY_CANDIDATE_PATTERN,
                    )
                    if not candidates:
                        continue
                    count_value, count_span, _ = candidates[0]
                    if (
                        count_value >= 0
                        and count_value.is_integer()
                    ):
                        assign(
                            field_name,
                            count_value,
                            _SummaryValueSource(
                                field_name=field_name,
                                line_index=line_index,
                                span=(
                                    match.end() + count_span[0],
                                    match.end() + count_span[1],
                                ),
                                polygon=bounds,
                                method="same_line",
                            ),
                        )
                        if len(candidates) >= 2:
                            amount, amount_span, _ = candidates[-1]
                            item_count_totals.append(
                                (
                                    amount,
                                    _SummaryValueSource(
                                        field_name=field_name,
                                        line_index=line_index,
                                        span=(
                                            match.end() + amount_span[0],
                                            match.end() + amount_span[1],
                                        ),
                                        polygon=bounds,
                                        method="same_line",
                                    ),
                                )
                            )
                    continue
                if values[field_name] is not None:
                    continue
                value_match = cls.SUMMARY_NUMBER_PATTERN.match(value_text)
                if value_match is None:
                    continue
                value = cls.parse_number(value_match.group("value"))
                if value is None:
                    continue
                value_span = value_match.span("value")
                assign(
                    field_name,
                    value,
                    _SummaryValueSource(
                        field_name=field_name,
                        line_index=line_index,
                        span=(
                            match.end() + value_span[0],
                            match.end() + value_span[1],
                        ),
                        polygon=bounds,
                        method="same_line",
                    ),
                )

        if values["total"] is None and item_count_totals:
            amount, source = item_count_totals[0]
            assign("total", amount, source)

        for location_index, (field_name, _, _) in enumerate(
            label_locations
        ):
            needs_geometry = values[field_name] is None or (
                field_name == "item_count"
                and values["total"] is None
            )
            if not needs_geometry:
                continue
            candidates = cls._visual_row_candidates(
                lines,
                line_labels,
                label_locations,
                location_index,
                values,
                used_numeric_lines,
            )
            if field_name == "item_count":
                count_candidate: _VisualNumericCandidate | None = None
                if values[field_name] is None and len(candidates) >= 2:
                    count_candidates = [
                        candidate
                        for candidate in candidates
                        if candidate.value >= 0
                        and candidate.value.is_integer()
                        and not cls._is_monetary_formatted(
                            candidate.text
                        )
                    ]
                    if not count_candidates:
                        count_candidates = [
                            candidate
                            for candidate in candidates
                            if candidate.value >= 0
                            and candidate.value.is_integer()
                        ]
                    if count_candidates:
                        count_candidate = min(
                            count_candidates,
                            key=lambda candidate: (
                                candidate.horizontal_gap,
                                candidate.vertical_distance,
                            ),
                        )
                        if assign(
                            field_name,
                            count_candidate.value,
                            _SummaryValueSource(
                                field_name=field_name,
                                line_index=count_candidate.line_index,
                                span=count_candidate.span,
                                polygon=count_candidate.bounds,
                                method="visual_row_geometry",
                            ),
                        ):
                            used_numeric_lines.add(
                                count_candidate.line_index
                            )

                if values[field_name] is None:
                    continue
                amount_candidates = [
                    candidate
                    for candidate in candidates
                    if count_candidate is None
                    or candidate.line_index != count_candidate.line_index
                ]
                if not amount_candidates:
                    continue
                formatted_candidates = [
                    candidate
                    for candidate in amount_candidates
                    if cls._is_monetary_formatted(candidate.text)
                ]
                amount_candidate = max(
                    formatted_candidates or amount_candidates,
                    key=lambda candidate: candidate.bounds[0],
                )
                if assign(
                    "total",
                    amount_candidate.value,
                    _SummaryValueSource(
                        field_name=field_name,
                        line_index=amount_candidate.line_index,
                        span=amount_candidate.span,
                        polygon=amount_candidate.bounds,
                        method="visual_row_geometry",
                    ),
                ):
                    used_numeric_lines.add(amount_candidate.line_index)
                continue

            if values[field_name] is not None or not candidates:
                continue
            candidate = candidates[0]
            if assign(
                field_name,
                candidate.value,
                _SummaryValueSource(
                    field_name=field_name,
                    line_index=candidate.line_index,
                    span=candidate.span,
                    polygon=candidate.bounds,
                    method="visual_row_geometry",
                ),
            ):
                used_numeric_lines.add(candidate.line_index)

        for location_index, (field_name, line_index, _) in enumerate(
            label_locations
        ):
            needs_adjacent = values[field_name] is None or (
                field_name == "item_count"
                and values["total"] is None
            )
            if not needs_adjacent:
                continue
            next_index = line_index + 1
            if field_name == "item_count":
                adjacent: list[
                    tuple[int, float, str, tuple[int, int]]
                ] = []
                while (
                    next_index < len(lines)
                    and not line_labels[next_index]
                ):
                    if next_index in used_numeric_lines:
                        next_index += 1
                        continue
                    match = cls.NUMERIC_LINE_PATTERN.fullmatch(
                        lines[next_index][0]
                    )
                    if match is None:
                        break
                    value = cls.parse_number(match.group("value"))
                    if value is not None:
                        adjacent.append(
                            (
                                next_index,
                                value,
                                lines[next_index][0],
                                match.span("value"),
                            )
                        )
                    next_index += 1

                if values[field_name] is None and len(adjacent) >= 2:
                    count_candidate = next(
                        (
                            candidate
                            for candidate in adjacent
                            if candidate[1] >= 0
                            and candidate[1].is_integer()
                            and not cls._is_monetary_formatted(
                                candidate[2]
                            )
                        ),
                        None,
                    )
                    if count_candidate is not None:
                        count_index, count_value, _, count_span = (
                            count_candidate
                        )
                        if assign(
                            field_name,
                            count_value,
                            _SummaryValueSource(
                                field_name=field_name,
                                line_index=count_index,
                                span=count_span,
                                polygon=lines[count_index][1],
                                method="adjacent_line",
                            ),
                        ):
                            used_numeric_lines.add(count_index)

                if values[field_name] is None:
                    continue
                amount_candidates = [
                    candidate
                    for candidate in adjacent
                    if candidate[0] not in used_numeric_lines
                ]
                if amount_candidates:
                    formatted_candidates = [
                        candidate
                        for candidate in amount_candidates
                        if cls._is_monetary_formatted(candidate[2])
                    ]
                    amount_index, amount, _, amount_span = (
                        (formatted_candidates or amount_candidates)[-1]
                    )
                    if assign(
                        "total",
                        amount,
                        _SummaryValueSource(
                            field_name=field_name,
                            line_index=amount_index,
                            span=amount_span,
                            polygon=lines[amount_index][1],
                            method="adjacent_line",
                        ),
                    ):
                        used_numeric_lines.add(amount_index)
                continue

            numeric_run: list[
                tuple[int, float, tuple[int, int]]
            ] = []
            while next_index < len(lines) and not line_labels[next_index]:
                match = cls.NUMERIC_LINE_PATTERN.fullmatch(
                    lines[next_index][0]
                )
                if match is None:
                    break
                value = cls.parse_number(match.group("value"))
                if value is not None:
                    numeric_run.append(
                        (next_index, value, match.span("value"))
                    )
                next_index += 1
            if len(numeric_run) != 1:
                continue
            numeric_index, value, value_span = numeric_run[0]
            if numeric_index in used_numeric_lines:
                continue
            if assign(
                field_name,
                value,
                _SummaryValueSource(
                    field_name=field_name,
                    line_index=numeric_index,
                    span=value_span,
                    polygon=lines[numeric_index][1],
                    method="adjacent_line",
                ),
            ):
                used_numeric_lines.add(numeric_index)

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
                r"\s*-\s*(?P<time>\d{2}:\d{2})\b"
            ),
            "%d.%m.%y",
            "%H:%M",
        ),
        (
            re.compile(
                r"\b(?P<date>\d{1,2}\s+[A-Za-z]{3}\s+\d{2})"
                r"\s+(?P<time>\d{2}:\d{2}(?::\d{2})?)\b",
                re.IGNORECASE,
            ),
            "%d %b %y",
            None,
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
    def extract_datetime(
        cls,
        content: str,
    ) -> tuple[date | None, time | None]:
        for pattern, date_format, fixed_time_format in (
            cls.DATE_TIME_PATTERNS
        ):
            match = pattern.search(content)

            if not match:
                continue

            try:
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
            except ValueError:
                continue
            return parsed_date, parsed_time

        return None, None

    @classmethod
    def parse(
        cls,
        content: str,
        pages: Sequence[Any] | None = None,
    ) -> Receipt:
        normalized_content, _ = cls.normalize_content(content)
        item_lines = cls._item_lines(normalized_content, pages)
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
        conservative_run: list[ReceiptItem] = []
        for line in item_lines:
            item = cls.parse_item_line(line)
            if item is not None:
                if conservative_run:
                    if len(conservative_run) >= 2:
                        items.extend(conservative_run)
                    conservative_run = []
                items.append(item)
                continue

            item = cls.parse_item_line(line, allow_conservative=True)
            if item is not None:
                conservative_run.append(item)
            elif conservative_run:
                if len(conservative_run) >= 2:
                    items.extend(conservative_run)
                conservative_run = []
        if len(conservative_run) >= 2:
            items.extend(conservative_run)

        transaction_date, transaction_time = (
            cls.extract_datetime(normalized_content)
        )

        first_line = item_lines[0] if item_lines else (lines[0] if lines else None)
        first_line_item = (
            cls.parse_item_line(first_line) is not None
            if first_line is not None
            else False
        )
        if first_line is not None and not first_line_item:
            first_candidate = cls.parse_item_line(
                first_line,
                allow_conservative=True,
            )
            first_line_item = (
                first_candidate is not None
                and first_candidate.source == "ocr_text_fallback_pattern_c"
            )
        merchant_name: str | None = None
        if first_line is not None:
            payment_candidate = cls.TRAILING_AMOUNT_PATTERN.sub(
                "",
                first_line,
            ).strip()
            is_payment_method = (
                cls.PAYMENT_METHOD_PATTERN.fullmatch(payment_candidate)
                is not None
                or re.fullmatch(
                    r"BAYAR\s*\(\s*CASH\s*\)",
                    payment_candidate,
                    re.IGNORECASE,
                )
                is not None
            )
            has_date = cls.extract_datetime(first_line)[0] is not None
            if (
                not first_line_item
                and not cls._labels_on_line(first_line)
                and not is_payment_method
                and not has_date
                and re.search(r"[A-Za-z]", first_line)
            ):
                merchant_name = first_line

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
                payment_method=cls._payment_method(
                    normalized_content,
                    pages,
                ),
            ),
            items=items,
            extraction_method="ocr_text_fallback",
            confidence=None,
        )

        return receipt
import re

from app.schemas.receipt import Receipt


class ReceiptMerger:
    @staticmethod
    def merge(
        primary: Receipt,
        fallback: Receipt,
    ) -> Receipt:
        if primary.merchant.name is None:
            primary.merchant.name = fallback.merchant.name

        if primary.merchant.address is None:
            primary.merchant.address = fallback.merchant.address

        if primary.merchant.phone is None:
            primary.merchant.phone = fallback.merchant.phone

        if primary.transaction.date is None:
            primary.transaction.date = fallback.transaction.date

        if primary.transaction.time is None:
            primary.transaction.time = fallback.transaction.time

        transaction_fields = [
            "subtotal",
            "discount",
            "tax",
            "tip",
            "total",
            "cash",
            "change",
            "currency",
            "payment_method",
        ]

        for field_name in transaction_fields:
            primary_value = getattr(
                primary.transaction,
                field_name,
            )

            fallback_value = getattr(
                fallback.transaction,
                field_name,
            )

            if primary_value is None and fallback_value is not None:
                setattr(
                    primary.transaction,
                    field_name,
                    fallback_value,
                )

        if not primary.items:
            primary.items = fallback.items
        elif fallback.items and not all(
            item.description_raw
            and item.quantity is not None
            and item.unit_price is not None
            and item.total_price is not None
            for item in primary.items
        ):
            ReceiptMerger._fill_missing_item_fields(primary, fallback)

        if fallback.extraction_method == "ocr_text_fallback":
            primary.extraction_method = (
                "prebuilt_receipt_with_ocr_fallback"
            )

        return primary

    @staticmethod
    def _normalized_description(value: str | None) -> str:
        if value is None:
            return ""
        return re.sub(r"[^\w]+", "", value.casefold())

    @classmethod
    def _fill_missing_item_fields(
        cls,
        primary: Receipt,
        fallback: Receipt,
    ) -> None:
        unused_fallback = set(range(len(fallback.items)))
        matched_fallback: set[int] = set()

        for primary_item in primary.items:
            description = cls._normalized_description(
                primary_item.description_normalized
                or primary_item.description_raw
            )
            if not description:
                continue
            match_index = next(
                (
                    index
                    for index in sorted(unused_fallback)
                    if cls._normalized_description(
                        fallback.items[index].description_normalized
                        or fallback.items[index].description_raw
                    )
                    == description
                ),
                None,
            )
            if match_index is None:
                continue

            unused_fallback.remove(match_index)
            matched_fallback.add(match_index)
            fallback_item = fallback.items[match_index]
            fields_filled = False
            for field_name in (
                "description_raw",
                "description_normalized",
                "quantity",
                "unit_price",
                "total_price",
            ):
                if (
                    getattr(primary_item, field_name) is None
                    and getattr(fallback_item, field_name) is not None
                ):
                    setattr(
                        primary_item,
                        field_name,
                        getattr(fallback_item, field_name),
                    )
                    fields_filled = True
            if fields_filled and "ocr_text_fallback" not in primary_item.source:
                primary_item.source = (
                    f"{primary_item.source}+ocr_text_fallback"
                )
            if (
                fields_filled
                and "derived_unit_price" in fallback_item.source
                and "derived_unit_price" not in primary_item.source
            ):
                primary_item.source = (
                    f"{primary_item.source}+derived_unit_price"
                )

        if len(primary.items) < len(fallback.items):
            primary.items.extend(
                fallback.items[index]
                for index in sorted(unused_fallback)
                if index not in matched_fallback
            )
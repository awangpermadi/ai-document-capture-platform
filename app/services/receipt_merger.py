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

        if not primary.items and fallback.items:
            primary.items = fallback.items

        if fallback.extraction_method == "ocr_text_fallback":
            primary.extraction_method = (
                "prebuilt_receipt_with_ocr_fallback"
            )

        return primary
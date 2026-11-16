from app.schemas.receipt import Receipt


class ReceiptExtractionValidator:
    CRITICAL_CONFIDENCE_THRESHOLD = 0.70

    @classmethod
    def validate(cls, receipt: Receipt) -> Receipt:
        reasons: list[str] = []

        if not receipt.merchant.name:
            reasons.append("Merchant name was not detected")

        if receipt.transaction.total is None:
            reasons.append("Transaction total was not detected")
        elif receipt.transaction.total <= 0:
            reasons.append("Transaction total must be greater than zero")

        if not receipt.items:
            reasons.append("No line items were extracted")

        for index, item in enumerate(receipt.items, start=1):
            if not item.description_raw:
                reasons.append(
                    f"Description for item {index} was not detected"
                )

            if item.quantity is None:
                reasons.append(
                    f"Quantity for item {index} was not detected"
                )

            if (
                item.confidence is not None
                and item.confidence
                < cls.CRITICAL_CONFIDENCE_THRESHOLD
            ):
                reasons.append(
                    f"Item {index} confidence is below "
                    f"{cls.CRITICAL_CONFIDENCE_THRESHOLD:.0%}"
                )

        if (
            receipt.confidence is not None
            and receipt.confidence
            < cls.CRITICAL_CONFIDENCE_THRESHOLD
        ):
            reasons.append(
                "Overall extraction confidence is below "
                f"{cls.CRITICAL_CONFIDENCE_THRESHOLD:.0%}"
            )

        receipt.requires_review = len(reasons) > 0
        receipt.review_reasons = reasons

        return receipt
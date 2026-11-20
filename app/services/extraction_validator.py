import math

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
            elif item.quantity <= 0:
                reasons.append(
                    f"Quantity for item {index} must be greater than zero"
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
                item.unit_price is None
                and item.quantity is not None
                and item.quantity > 0
                and item.total_price is not None
            ):
                item.unit_price = item.total_price / item.quantity
                if "derived_unit_price" not in item.source:
                    item.source = (
                        f"{item.source}_derived_unit_price"
                    )
                reasons.append(
                    f"Unit price for item {index} was derived from "
                    "quantity and total price"
                )
            elif item.unit_price is None:
                reasons.append(
                    f"Unit price for item {index} was not detected"
                )
            elif "derived_unit_price" in item.source:
                reasons.append(
                    f"Unit price for item {index} was derived from "
                    "quantity and total price"
                )

            if item.total_price is None:
                reasons.append(
                    f"Total price for item {index} was not detected"
                )

            if (
                item.quantity is not None
                and item.quantity > 0
                and item.unit_price is not None
                and item.total_price is not None
                and not math.isclose(
                    item.quantity * item.unit_price,
                    item.total_price,
                    rel_tol=0.001,
                    abs_tol=1.0,
                )
            ):
                reasons.append(
                    f"Quantity, unit price, and total price for item "
                    f"{index} are inconsistent"
                )

        if receipt.items and all(
            item.total_price is not None for item in receipt.items
        ):
            expected_items_total = receipt.transaction.subtotal
            expected_field = "subtotal"
            if expected_items_total is None and all(
                value in (None, 0)
                for value in (
                    receipt.transaction.tax,
                    receipt.transaction.discount,
                    receipt.transaction.tip,
                )
            ):
                expected_items_total = receipt.transaction.total
                expected_field = "total"
            items_total = sum(
                item.total_price or 0 for item in receipt.items
            )
            if (
                expected_items_total is not None
                and not math.isclose(
                    items_total,
                    expected_items_total,
                    rel_tol=0.001,
                    abs_tol=1.0,
                )
            ):
                reasons.append(
                    f"Sum of item totals does not match the transaction "
                    f"{expected_field}"
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
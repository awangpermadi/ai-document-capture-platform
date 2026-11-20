import math

from app.schemas.receipt import Receipt


class ReceiptReconciler:
    TOTAL_RECONCILIATION_REASON = (
        "Transaction total reconciled from consistent receipt values."
    )
    CHANGE_RECONCILIATION_REASON = (
        "Transaction change reconciled from consistent receipt values."
    )
    AMOUNT_TOLERANCE = 1.0
    RELATIVE_TOLERANCE = 0.001

    @classmethod
    def reconcile(
        cls,
        receipt: Receipt,
        *,
        structured_total: float | None,
        structured_change: float | None = None,
        ocr_receipt: Receipt | None = None,
    ) -> list[str]:
        signals = cls._total_signals(receipt, ocr_receipt)
        consistent_total = cls._consistent_total(signals)
        reasons: list[str] = []
        current_total = receipt.transaction.total

        if consistent_total is not None:
            if current_total is None:
                receipt.transaction.total = consistent_total
            elif (
                not cls._amounts_match(current_total, consistent_total)
                or (
                    structured_total is not None
                    and not cls._amounts_match(
                        structured_total,
                        consistent_total,
                    )
                )
            ):
                receipt.transaction.total = consistent_total
                reasons.append(cls.TOTAL_RECONCILIATION_REASON)

        if (
            structured_change is not None
            and ocr_receipt is not None
            and ocr_receipt.transaction.change is not None
            and receipt.transaction.change is not None
            and cls._amounts_match(
                receipt.transaction.change,
                structured_change,
            )
            and not cls._amounts_match(
                receipt.transaction.change,
                ocr_receipt.transaction.change,
            )
        ):
            change_replacement = cls._validated_ocr_change(
                receipt,
                ocr_receipt,
                consistent_total,
            )
            if change_replacement is not None:
                receipt.transaction.change = change_replacement
                reasons.append(cls.CHANGE_RECONCILIATION_REASON)

        if receipt.transaction.change is None:
            cash = receipt.transaction.cash
            total = receipt.transaction.total
            if (
                cls._is_positive_amount(cash)
                and cls._is_positive_amount(total)
                and cash >= total
            ):
                receipt.transaction.change = cash - total

        return reasons

    @classmethod
    def _total_signals(
        cls,
        receipt: Receipt,
        ocr_receipt: Receipt | None,
    ) -> list[tuple[str, float]]:
        signals: list[tuple[str, float]] = []
        transaction = receipt.transaction
        cash_change_total = cls._cash_change_total(receipt)
        if cash_change_total is not None:
            signals.append(("cash_minus_change", cash_change_total))
            cls._append_matching_amount_signals(
                signals,
                receipt,
                cash_change_total,
            )
        elif not any(
            value is not None and value != 0
            for value in (
                transaction.discount,
                transaction.tax,
                transaction.tip,
            )
        ):
            cls._append_amount_signals(signals, receipt)

        if ocr_receipt is None:
            return signals

        ocr_total = ocr_receipt.transaction.total
        ocr_cash_change_total = cls._cash_change_total(ocr_receipt)
        if cls._is_positive_amount(ocr_total):
            signals.append(("ocr_total", ocr_total))
        if (
            ocr_cash_change_total is not None
            and (
                cash_change_total is None
                or not cls._amounts_match(
                    cash_change_total,
                    ocr_cash_change_total,
                )
            )
        ):
            signals.append(
                ("ocr_cash_minus_change", ocr_cash_change_total)
            )

        anchors = [
            value
            for value in (
                cash_change_total,
                ocr_cash_change_total,
                ocr_total,
            )
            if cls._is_positive_amount(value)
        ]
        if anchors:
            cls._append_matching_ocr_amount_signals(
                signals,
                receipt,
                ocr_receipt,
                anchors,
            )

        return signals

    @classmethod
    def _append_amount_signals(
        cls,
        signals: list[tuple[str, float]],
        receipt: Receipt,
    ) -> None:
        subtotal = receipt.transaction.subtotal
        if cls._is_positive_amount(subtotal):
            signals.append(("subtotal", subtotal))

        items_total = cls._items_total(receipt)
        if items_total is not None:
            signals.append(("items_total", items_total))

    @classmethod
    def _append_matching_amount_signals(
        cls,
        signals: list[tuple[str, float]],
        receipt: Receipt,
        expected: float,
    ) -> None:
        subtotal = receipt.transaction.subtotal
        if (
            cls._is_positive_amount(subtotal)
            and cls._amounts_match(subtotal, expected)
        ):
            signals.append(("subtotal", subtotal))

        items_total = cls._items_total(receipt)
        if (
            items_total is not None
            and cls._amounts_match(items_total, expected)
        ):
            signals.append(("items_total", items_total))

    @classmethod
    def _append_matching_ocr_amount_signals(
        cls,
        signals: list[tuple[str, float]],
        receipt: Receipt,
        ocr_receipt: Receipt,
        anchors: list[float],
    ) -> None:
        existing_names = {name for name, _ in signals}
        candidates = (
            (
                "subtotal",
                receipt.transaction.subtotal,
            ),
            (
                "ocr_subtotal",
                ocr_receipt.transaction.subtotal,
            ),
            ("items_total", cls._items_total(receipt)),
            ("ocr_items_total", cls._items_total(ocr_receipt)),
        )
        for name, value in candidates:
            if (
                name in existing_names
                or not cls._is_positive_amount(value)
                or not any(
                    cls._amounts_match(value, anchor)
                    for anchor in anchors
                )
            ):
                continue
            signals.append((name, value))
            existing_names.add(name)

    @classmethod
    def _validated_ocr_change(
        cls,
        receipt: Receipt,
        ocr_receipt: Receipt,
        consistent_total: float | None,
    ) -> float | None:
        ocr_change = ocr_receipt.transaction.change
        cash = (
            ocr_receipt.transaction.cash
            if cls._is_positive_amount(ocr_receipt.transaction.cash)
            else receipt.transaction.cash
        )
        total = consistent_total or receipt.transaction.total
        if (
            ocr_change is None
            or not math.isfinite(ocr_change)
            or ocr_change < 0
            or not cls._is_positive_amount(cash)
            or not cls._is_positive_amount(total)
            or cash < total
            or not cls._amounts_match(ocr_change, cash - total)
        ):
            return None

        has_independent_amount = any(
            name in {
                "subtotal",
                "ocr_subtotal",
                "items_total",
                "ocr_items_total",
                "ocr_total",
            }
            and cls._amounts_match(value, total)
            for name, value in cls._total_signals(receipt, ocr_receipt)
        )
        return ocr_change if has_independent_amount else None

    @classmethod
    def _cash_change_total(cls, receipt: Receipt) -> float | None:
        cash = receipt.transaction.cash
        change = receipt.transaction.change
        if (
            cls._is_positive_amount(cash)
            and change is not None
            and math.isfinite(change)
            and 0 <= change <= cash
        ):
            total = cash - change
            return total if cls._is_positive_amount(total) else None
        return None

    @classmethod
    def _items_total(cls, receipt: Receipt) -> float | None:
        if not receipt.items or any(
            item.total_price is None
            or not math.isfinite(item.total_price)
            for item in receipt.items
        ):
            return None
        total = sum(item.total_price for item in receipt.items)
        return total if cls._is_positive_amount(total) else None

    @classmethod
    def _consistent_total(
        cls,
        signals: list[tuple[str, float]],
    ) -> float | None:
        groups: dict[frozenset[str], float] = {}
        for _, candidate in signals:
            supporters = [
                (name, value)
                for name, value in signals
                if cls._amounts_match(candidate, value)
            ]
            if len(supporters) < 2:
                continue
            group_key = frozenset(name for name, _ in supporters)
            groups[group_key] = sum(
                value for _, value in supporters
            ) / len(supporters)

        if not groups:
            return None
        strongest_count = max(len(group) for group in groups)
        strongest = [
            total
            for group, total in groups.items()
            if len(group) == strongest_count
        ]
        return strongest[0] if len(strongest) == 1 else None

    @classmethod
    def _amounts_match(cls, left: float, right: float) -> bool:
        return math.isclose(
            left,
            right,
            rel_tol=cls.RELATIVE_TOLERANCE,
            abs_tol=cls.AMOUNT_TOLERANCE,
        )

    @staticmethod
    def _is_positive_amount(value: float | None) -> bool:
        return (
            value is not None
            and math.isfinite(value)
            and value > 0
        )

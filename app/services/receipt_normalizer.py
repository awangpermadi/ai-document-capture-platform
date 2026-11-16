import logging
from collections.abc import Mapping
from datetime import date, datetime, time
from typing import Any

from azure.ai.documentintelligence.models import AnalyzeResult, DocumentField

from app.schemas.receipt import Merchant, Receipt, ReceiptItem, Transaction

logger = logging.getLogger(__name__)

AzureField = DocumentField | Mapping[str, Any]


class ReceiptNormalizer:
    def normalize(self, result: AnalyzeResult) -> Receipt:
        documents = self._attribute(result, "documents")
        document = documents[0] if documents else None
        document_fields = self._attribute(document, "fields")
        fields = document_fields if isinstance(document_fields, Mapping) else {}
        logger.debug(
            "Azure receipt structured fields returned: %s",
            sorted(str(name) for name in fields),
        )

        subtotal_field = self._get_field(fields, "Subtotal")
        tax_field = self._get_field(fields, "TotalTax")
        tip_field = self._get_field(fields, "Tip")
        total_field = self._get_field(fields, "Total")

        return Receipt(
            merchant=Merchant(
                name=self._text(self._get_field(fields, "MerchantName")),
                address=self._address(self._get_field(fields, "MerchantAddress")),
                phone=self._text(
                    self._get_field(fields, "MerchantPhoneNumber"),
                    "value_phone_number",
                ),
            ),
            transaction=Transaction(
                date=self._date(self._get_field(fields, "TransactionDate")),
                time=self._time(self._get_field(fields, "TransactionTime")),
                subtotal=self._number(subtotal_field),
                tax=self._number(tax_field),
                tip=self._number(tip_field),
                total=self._number(total_field),
                currency=self._currency_code(
                    subtotal_field,
                    tax_field,
                    tip_field,
                    total_field,
                ),
            ),
            items=self._items(self._get_field(fields, "Items")),
            confidence=self._confidence(self._attribute(document, "confidence")),
        )

    @staticmethod
    def _attribute(value: Any, name: str) -> Any:
        if value is None:
            return None

        attribute = getattr(value, name, None)
        if attribute is not None:
            return attribute
        if isinstance(value, Mapping):
            camel_name = name.split("_")[0] + "".join(
                part.title() for part in name.split("_")[1:]
            )
            return value.get(name, value.get(camel_name))
        return None

    @classmethod
    def _get_field(
        cls,
        fields: Mapping[str, Any],
        name: str,
    ) -> AzureField | None:
        field = fields.get(name)
        return field if isinstance(field, (DocumentField, Mapping)) else None

    @classmethod
    def _value(cls, field: AzureField | None, *attributes: str) -> Any:
        if field is None:
            return None

        for attribute in attributes:
            value = cls._attribute(field, attribute)
            if value is not None:
                return value
        return None

    @classmethod
    def _text(
        cls,
        field: AzureField | None,
        preferred_attribute: str = "value_string",
    ) -> str | None:
        value = cls._value(field, preferred_attribute, "content")
        return value if isinstance(value, str) else None

    @classmethod
    def _address(cls, field: AzureField | None) -> str | None:
        content = cls._value(field, "content")
        if isinstance(content, str):
            return content

        address = cls._value(field, "value_address")
        if isinstance(address, str):
            return address
        if address is None:
            return None

        parts = (
            cls._attribute(address, attribute)
            for attribute in (
                "street_address",
                "city",
                "state",
                "postal_code",
                "country_region",
            )
        )
        formatted = ", ".join(
            part for part in parts if isinstance(part, str) and part
        )
        return formatted or None

    @classmethod
    def _number(cls, field: AzureField | None) -> float | None:
        currency = cls._value(field, "value_currency")
        value = cls._attribute(currency, "amount")
        if value is None:
            value = cls._value(field, "value_number", "value_integer")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)

    @classmethod
    def _currency_code(cls, *fields: AzureField | None) -> str | None:
        for field in fields:
            currency = cls._value(field, "value_currency")
            code = cls._attribute(currency, "currency_code")
            if isinstance(code, str):
                return code
        return None

    @classmethod
    def _date(cls, field: AzureField | None) -> date | None:
        value = cls._value(field, "value_date")
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            try:
                return date.fromisoformat(value)
            except ValueError:
                return None
        return None

    @classmethod
    def _time(cls, field: AzureField | None) -> time | None:
        value = cls._value(field, "value_time")
        if isinstance(value, time):
            return value
        if isinstance(value, str):
            try:
                return time.fromisoformat(value)
            except ValueError:
                return None
        return None

    @classmethod
    def _items(cls, field: AzureField | None) -> list[ReceiptItem]:
        values = cls._value(field, "value_array")
        if not isinstance(values, (list, tuple)):
            return []

        item_field_names: set[str] = set()
        item_fields_list = [
            cls._attribute(item, "value_object")
            for item in values
        ]
        for item_fields in item_fields_list:
            if isinstance(item_fields, Mapping):
                item_field_names.update(str(name) for name in item_fields)
        logger.debug(
            "Azure receipt item structured fields returned: %s",
            sorted(item_field_names),
        )

        items: list[ReceiptItem] = []
        for value, item_fields in zip(values, item_fields_list):
            if not isinstance(item_fields, Mapping):
                continue

            items.append(
                ReceiptItem(
                    description_raw=cls._text(
                        cls._get_field(item_fields, "Description")
                    ),
                    description_normalized=None,
                    quantity=cls._number(cls._get_field(item_fields, "Quantity")),
                    unit_price=cls._number(cls._get_field(item_fields, "Price")),
                    total_price=cls._number(
                        cls._get_field(item_fields, "TotalPrice")
                    ),
                    confidence=cls._confidence(
                        cls._attribute(value, "confidence")
                    ),
                )
            )
        return items

    @staticmethod
    def _confidence(value: Any) -> float | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)

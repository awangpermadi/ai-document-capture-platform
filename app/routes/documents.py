import logging
from collections.abc import Mapping
from datetime import date, datetime, time
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool
from azure.ai.documentintelligence.models import DocumentField

from app.schemas.receipt import Receipt
from app.services.document_intelligence import (
    AzureDocumentIntelligenceService,
    DocumentIntelligenceError,
)
from app.services.extraction_validator import ReceiptExtractionValidator
from app.services.receipt_merger import ReceiptMerger
from app.services.receipt_normalizer import ReceiptNormalizer
from app.services.receipt_text_parser import ReceiptTextParser

router = APIRouter(
    prefix="/documents",
    tags=["Documents"]
)

UPLOAD_DIRECTORY = Path("uploads")
UPLOAD_DIRECTORY.mkdir(parents=True, exist_ok=True)

ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "application/pdf",
}

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

logger = logging.getLogger(__name__)


def _debug_value(value: Any) -> Any:
    if isinstance(value, DocumentField):
        return _debug_field(value)
    if isinstance(value, Mapping):
        return {
            str(name): _debug_value(field)
            for name, field in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_debug_value(item) for item in value]
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value

    currency_amount = getattr(value, "amount", None)
    currency_code = getattr(value, "currency_code", None)
    if currency_amount is not None or currency_code is not None:
        return {
            "amount": currency_amount,
            "currency_code": currency_code,
        }

    address_attributes = (
        "street_address",
        "city",
        "state",
        "postal_code",
        "country_region",
    )
    address = {
        name: getattr(value, name, None)
        for name in address_attributes
        if getattr(value, name, None) is not None
    }
    return address or None


def _debug_field(field: DocumentField) -> dict[str, Any]:
    value: Any = None
    for attribute in (
        "value_object",
        "value_array",
        "value_address",
        "value_currency",
        "value_string",
        "value_date",
        "value_time",
        "value_number",
        "value_integer",
        "value_boolean",
        "value_phone_number",
        "value_country_region",
        "value_selection_group",
        "value_selection_mark",
        "value_signature",
    ):
        candidate = getattr(field, attribute, None)
        if candidate is not None:
            value = _debug_value(candidate)
            break

    return {
        "content": field.content,
        "value": value,
        "confidence": field.confidence,
    }


def _debug_fields(fields: Mapping[str, Any]) -> dict[str, Any]:
    return {
        str(name): _debug_field(field)
        for name, field in fields.items()
        if isinstance(field, DocumentField)
    }


@router.post("/upload")
async def upload_document(file: UploadFile = File(...)):

    # Validate file type
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=415,
            detail="Only JPG, PNG, and PDF files are supported."
        )

    content = await file.read()

    # Validate empty file
    if not content:
        raise HTTPException(
            status_code=400,
            detail="Uploaded file is empty."
        )

    # Validate file size
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail="Maximum file size is 10 MB."
        )

    # Generate unique filename
    extension = Path(file.filename or "").suffix.lower()

    stored_filename = f"{uuid4()}{extension}"

    destination = UPLOAD_DIRECTORY / stored_filename

    # Save file
    destination.write_bytes(content)

    return {
        "original_filename": file.filename,
        "stored_filename": stored_filename,
        "content_type": file.content_type,
        "size": len(content),
        "status": "uploaded"
    }


@router.post("/analyze", response_model=Receipt)
async def analyze_document(file: UploadFile = File(...)) -> Receipt:
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=415,
            detail="Only JPG, PNG, and PDF files are supported."
        )

    content = await file.read()

    if not content:
        raise HTTPException(
            status_code=400,
            detail="Uploaded file is empty."
        )

    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail="Maximum file size is 10 MB."
        )

    service = AzureDocumentIntelligenceService()
    try:
        result = await run_in_threadpool(service.analyze_document, content)
    except DocumentIntelligenceError:
        raise HTTPException(
            status_code=502,
            detail="Document analysis failed."
        ) from None

    azure_receipt = ReceiptNormalizer().normalize(result)
    raw_content = result.content

    if raw_content and raw_content.strip():
        try:
            fallback_receipt = ReceiptTextParser.parse(
                raw_content,
                pages=getattr(result, "pages", None),
            )
        except ValueError:
            logger.warning("OCR receipt text fallback parsing failed.")
            fallback_receipt = Receipt()

        final_receipt = ReceiptMerger.merge(azure_receipt, fallback_receipt)
    else:
        final_receipt = azure_receipt

    final_receipt = ReceiptExtractionValidator.validate(final_receipt)
    return final_receipt


@router.post("/debug-analysis")
async def debug_analyze_document(file: UploadFile = File(...)) -> dict[str, Any]:
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=415,
            detail="Only JPG, PNG, and PDF files are supported."
        )

    content = await file.read()

    if not content:
        raise HTTPException(
            status_code=400,
            detail="Uploaded file is empty."
        )

    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail="Maximum file size is 10 MB."
        )

    service = AzureDocumentIntelligenceService()
    try:
        result = await run_in_threadpool(service.analyze_document, content)
    except DocumentIntelligenceError:
        raise HTTPException(
            status_code=502,
            detail="Document analysis failed."
        ) from None

    documents = getattr(result, "documents", None) or []
    return {
        "content": result.content,
        "documents": [
            {
                "document_type": document.doc_type,
                "confidence": document.confidence,
                "fields": _debug_fields(document.fields or {}),
            }
            for document in documents
        ],
    }
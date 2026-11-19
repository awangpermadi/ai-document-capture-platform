import logging
from collections.abc import Awaitable, Mapping
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, TypeVar
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, UploadFile
from starlette.concurrency import run_in_threadpool
from azure.ai.documentintelligence.models import DocumentField
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db_session
from app.exceptions import (
    DocumentApprovalValidationError,
    DocumentNotFoundError,
    DocumentReviewPersistenceError,
    DocumentStateConflictError,
)
from app.models import DocumentStatus
from app.schemas.document import (
    DocumentActionResponse,
    DocumentApprovalRequest,
    DocumentDetail,
    DocumentListItem,
    DocumentProcessResponse,
    ReceiptCorrectionRequest,
)
from app.schemas.receipt import Receipt, ReceiptRead
from app.services.document_intelligence import (
    AzureDocumentIntelligenceService,
    DocumentIntelligenceError,
)
from app.services.document_review import DocumentReviewService
from app.services.receipt_extraction import ReceiptExtractionService
from app.services.receipt_persistence import ReceiptPersistenceService

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
_ResponseT = TypeVar("_ResponseT")


async def _execute_review(
    operation: Awaitable[_ResponseT],
) -> _ResponseT:
    try:
        return await operation
    except DocumentNotFoundError:
        raise HTTPException(
            status_code=404,
            detail="Document not found.",
        ) from None
    except DocumentStateConflictError as error:
        raise HTTPException(
            status_code=409,
            detail=str(error),
        ) from None
    except DocumentApprovalValidationError as error:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Document approval validation failed.",
                "reasons": error.errors,
            },
        ) from None
    except DocumentReviewPersistenceError:
        raise HTTPException(
            status_code=500,
            detail="Document review operation could not be completed.",
        ) from None
    except Exception:
        logger.exception("Unexpected document review endpoint failure.")
        raise HTTPException(
            status_code=500,
            detail="An unexpected server error occurred.",
        ) from None


def _parse_document_status(value: str | None) -> DocumentStatus | None:
    if value is None:
        return None
    try:
        return DocumentStatus[value.upper()]
    except KeyError:
        try:
            return DocumentStatus(value.lower())
        except ValueError:
            valid_statuses = ", ".join(status.name for status in DocumentStatus)
            raise HTTPException(
                status_code=422,
                detail=f"Invalid status. Valid values: {valid_statuses}.",
            ) from None


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

    try:
        extraction = await ReceiptExtractionService().extract(content)
    except DocumentIntelligenceError:
        raise HTTPException(
            status_code=502,
            detail="Document analysis failed."
        ) from None

    return extraction.receipt


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


@router.post("/process", response_model=DocumentProcessResponse)
async def process_document(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db_session),
) -> DocumentProcessResponse:
    content_type = file.content_type
    if content_type is None or content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=415,
            detail="Only JPG, PNG, and PDF files are supported.",
        )

    content = await file.read(MAX_FILE_SIZE + 1)
    if not content:
        raise HTTPException(
            status_code=400,
            detail="Uploaded file is empty.",
        )
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail="Maximum file size is 10 MB.",
        )

    original_filename = file.filename or "uploaded-document"
    accepted_extensions = {
        "image/jpeg": {".jpg", ".jpeg"},
        "image/png": {".png"},
        "application/pdf": {".pdf"},
    }
    original_extension = Path(original_filename).suffix.lower()
    extensions = accepted_extensions[content_type]
    extension = (
        original_extension
        if original_extension in extensions
        else next(iter(sorted(extensions)))
    )
    stored_filename = f"{uuid4()}{extension}"
    stored_path = UPLOAD_DIRECTORY / stored_filename

    try:
        UPLOAD_DIRECTORY.mkdir(parents=True, exist_ok=True)
        await run_in_threadpool(stored_path.write_bytes, content)
    except Exception:
        _remove_process_upload(stored_path)
        logger.exception("Failed to store uploaded document.")
        raise HTTPException(
            status_code=500,
            detail="Document could not be stored.",
        ) from None

    try:
        extraction = await ReceiptExtractionService().extract(content)
    except DocumentIntelligenceError:
        _remove_process_upload(stored_path)
        raise HTTPException(
            status_code=502,
            detail="Document analysis failed.",
        ) from None
    except ValueError:
        _remove_process_upload(stored_path)
        raise HTTPException(
            status_code=422,
            detail="Document could not be normalized.",
        ) from None
    except Exception:
        _remove_process_upload(stored_path)
        logger.exception("Unexpected document extraction failure.")
        raise HTTPException(
            status_code=500,
            detail="Document processing failed.",
        ) from None

    try:
        document = await ReceiptPersistenceService(session).persist(
            original_filename=original_filename,
            stored_filename=stored_filename,
            content_type=content_type,
            receipt=extraction.receipt,
            raw_ocr_content=extraction.raw_ocr_content,
        )
    except DocumentReviewPersistenceError:
        _remove_process_upload(stored_path)
        raise HTTPException(
            status_code=500,
            detail="Document persistence failed.",
        ) from None
    except Exception:
        _remove_process_upload(stored_path)
        logger.exception("Unexpected document persistence failure.")
        raise HTTPException(
            status_code=500,
            detail="Document persistence failed.",
        ) from None

    receipt_read = ReceiptRead.model_validate(extraction.receipt)
    if document.receipt is not None:
        persisted_items = sorted(
            document.receipt.items,
            key=lambda item: item.line_number,
        )
        for read_item, persisted_item in zip(
            receipt_read.items,
            persisted_items,
        ):
            read_item.id = persisted_item.id

    return DocumentProcessResponse(
        document_id=document.id,
        status=document.status.name,
        receipt=receipt_read,
        requires_review=extraction.receipt.requires_review,
        review_reasons=extraction.receipt.review_reasons,
        created_at=document.created_at,
    )


def _remove_process_upload(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.exception("Failed to clean up an unsuccessful document upload.")


@router.get("", response_model=list[DocumentListItem])
async def list_documents(
    status: str | None = Query(default=None),
    requires_review: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session),
) -> list[DocumentListItem]:
    return await _execute_review(
        DocumentReviewService(session).list_documents(
            status=_parse_document_status(status),
            requires_review=requires_review,
            limit=limit,
            offset=offset,
        )
    )


@router.get("/{document_id}", response_model=DocumentDetail)
async def get_document_detail(
    document_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> DocumentDetail:
    return await _execute_review(
        DocumentReviewService(session).get_document_detail(document_id)
    )


@router.put("/{document_id}/receipt", response_model=DocumentDetail)
async def update_receipt_correction(
    document_id: str,
    correction: ReceiptCorrectionRequest,
    reviewed_by: str = Header(alias="X-Reviewed-By"),
    session: AsyncSession = Depends(get_db_session),
) -> DocumentDetail:
    if not reviewed_by.strip():
        raise HTTPException(
            status_code=422,
            detail="X-Reviewed-By must not be empty.",
        )

    return await _execute_review(
        DocumentReviewService(session).update_receipt_correction(
            document_id,
            correction,
            reviewed_by,
        )
    )


@router.post(
    "/{document_id}/approve",
    response_model=DocumentActionResponse,
)
async def approve_document(
    document_id: str,
    request: DocumentApprovalRequest,
    session: AsyncSession = Depends(get_db_session),
) -> DocumentActionResponse:
    return await _execute_review(
        DocumentReviewService(session).approve_document(
            document_id,
            request.reviewed_by,
        )
    )
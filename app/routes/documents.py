from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, UploadFile

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
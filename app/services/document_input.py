import logging
import warnings
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from app.services.image_normalizer import normalize_image_for_analysis

logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 10 * 1024 * 1024
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".pdf"}
_DECLARED_CONTENT_TYPES = {
    "image/jpeg": "image/jpeg",
    "image/jpg": "image/jpeg",
    "image/pjpeg": "image/jpeg",
    "image/png": "image/png",
    "application/pdf": "application/pdf",
    "application/octet-stream": "application/octet-stream",
}
_FORMAT_CONTENT_TYPES = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
}
_CONTENT_TYPE_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "application/pdf": ".pdf",
}
_VALID_EXTENSIONS_BY_CONTENT_TYPE = {
    "image/jpeg": {".jpg", ".jpeg"},
    "image/png": {".png"},
    "application/pdf": {".pdf"},
}
_PDF_SIGNATURE = b"%PDF-"


class DocumentInputError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        detected_format: str | None = None,
        detected_content_type: str | None = None,
        width: int | None = None,
        height: int | None = None,
        image_mode: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detected_format = detected_format
        self.detected_content_type = detected_content_type
        self.width = width
        self.height = height
        self.image_mode = image_mode


@dataclass(frozen=True)
class ValidatedDocument:
    original_filename: str
    declared_content_type: str | None
    detected_content_type: str
    detected_format: str
    extension: str
    size_bytes: int
    width: int | None
    height: int | None
    image_mode: str | None
    original_content: bytes = field(repr=False)
    analysis_content: bytes = field(repr=False)
    normalization_applied: bool = False

    @property
    def storage_extension(self) -> str:
        return _CONTENT_TYPE_EXTENSIONS[self.detected_content_type]


class DocumentValidator:
    @classmethod
    def validate(
        cls,
        content: bytes,
        *,
        original_filename: str | None,
        declared_content_type: str | None,
    ) -> ValidatedDocument:
        if not content:
            raise DocumentInputError(
                "Uploaded file is empty.",
                status_code=400,
            )
        if len(content) > MAX_FILE_SIZE:
            raise DocumentInputError(
                "Maximum file size is 10 MB.",
                status_code=413,
            )

        filename = original_filename or ""
        extension = Path(filename).suffix.lower()
        declared = cls._normalize_declared_content_type(
            declared_content_type
        )
        if extension not in ALLOWED_EXTENSIONS:
            cls._log_rejection(
                filename=filename,
                declared_content_type=declared,
                extension=extension,
                detected_format=None,
                detected_content_type=None,
                size_bytes=len(content),
            )
            raise DocumentInputError(
                "Only JPG, PNG, and PDF files are supported.",
                status_code=415,
            )
        if declared is None:
            cls._log_rejection(
                filename=filename,
                declared_content_type=declared_content_type,
                extension=extension,
                detected_format=None,
                detected_content_type=None,
                size_bytes=len(content),
            )
            raise DocumentInputError(
                "Only JPG, PNG, and PDF files are supported.",
                status_code=415,
            )

        if content.startswith(_PDF_SIGNATURE):
            return cls._build_validated_document(
                content=content,
                filename=filename,
                declared_content_type=declared,
                extension=extension,
                detected_format="PDF",
                detected_content_type="application/pdf",
                width=None,
                height=None,
                image_mode=None,
                analysis_content=content,
                normalization_applied=False,
            )

        try:
            with warnings.catch_warnings():
                warnings.simplefilter(
                    "error",
                    Image.DecompressionBombWarning,
                )
                with Image.open(BytesIO(content)) as image:
                    image_format = image.format
                    image_mode = image.mode
                    width, height = image.size
                    image.verify()
                if image_format not in _FORMAT_CONTENT_TYPES:
                    cls._log_rejection(
                        filename=filename,
                        declared_content_type=declared,
                        extension=extension,
                        detected_format=image_format,
                        detected_content_type=None,
                        size_bytes=len(content),
                        width=width,
                        height=height,
                        image_mode=image_mode,
                    )
                    raise DocumentInputError(
                        "Unsupported image format.",
                        status_code=415,
                        detected_format=image_format,
                        width=width,
                        height=height,
                        image_mode=image_mode,
                    )
                if width <= 0 or height <= 0:
                    raise DocumentInputError(
                        "Uploaded image could not be decoded.",
                        status_code=422,
                        detected_format=image_format,
                        width=width,
                        height=height,
                        image_mode=image_mode,
                    )
                detected_content_type = _FORMAT_CONTENT_TYPES[image_format]
                normalized = normalize_image_for_analysis(
                    content,
                    detected_format=image_format,
                )
        except DocumentInputError:
            raise
        except (
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
        ) as error:
            cls._log_rejection(
                filename=filename,
                declared_content_type=declared,
                extension=extension,
                detected_format=None,
                detected_content_type=None,
                size_bytes=len(content),
            )
            raise DocumentInputError(
                "Uploaded image exceeds safe decoding limits.",
                status_code=422,
            ) from error
        except (
            UnidentifiedImageError,
            OSError,
            SyntaxError,
            ValueError,
        ) as error:
            cls._log_rejection(
                filename=filename,
                declared_content_type=declared,
                extension=extension,
                detected_format=None,
                detected_content_type=None,
                size_bytes=len(content),
            )
            raise DocumentInputError(
                "Uploaded file could not be decoded as a supported image.",
                status_code=422,
            ) from error

        return cls._build_validated_document(
            content=content,
            filename=filename,
            declared_content_type=declared,
            extension=extension,
            detected_format=image_format,
            detected_content_type=detected_content_type,
            width=width,
            height=height,
            image_mode=image_mode,
            analysis_content=normalized.content,
            normalization_applied=normalized.applied,
        )

    @staticmethod
    def _normalize_declared_content_type(
        content_type: str | None,
    ) -> str | None:
        value = (content_type or "").split(";", maxsplit=1)[0].strip().lower()
        return value if value in _DECLARED_CONTENT_TYPES else None

    @classmethod
    def _build_validated_document(
        cls,
        *,
        content: bytes,
        filename: str,
        declared_content_type: str | None,
        extension: str,
        detected_format: str,
        detected_content_type: str,
        width: int | None,
        height: int | None,
        image_mode: str | None,
        analysis_content: bytes,
        normalization_applied: bool,
    ) -> ValidatedDocument:
        validated = ValidatedDocument(
            original_filename=filename,
            declared_content_type=declared_content_type,
            detected_content_type=detected_content_type,
            detected_format=detected_format,
            extension=extension,
            size_bytes=len(content),
            width=width,
            height=height,
            image_mode=image_mode,
            original_content=content,
            analysis_content=analysis_content,
            normalization_applied=normalization_applied,
        )
        mismatch = (
            declared_content_type != "application/octet-stream"
            and _DECLARED_CONTENT_TYPES.get(declared_content_type)
            != detected_content_type
        ) or extension not in _VALID_EXTENSIONS_BY_CONTENT_TYPE[
            detected_content_type
        ]
        log = logger.warning if mismatch else logger.info
        log(
            "Validated document input: filename=%r declared_mime=%s "
            "extension=%s detected_format=%s detected_mime=%s "
            "size_bytes=%d width=%s height=%s image_mode=%s "
            "normalization_applied=%s",
            cls._safe_filename(filename),
            declared_content_type,
            extension,
            detected_format,
            detected_content_type,
            len(content),
            width,
            height,
            image_mode,
            normalization_applied,
        )
        return validated

    @classmethod
    def _log_rejection(
        cls,
        *,
        filename: str,
        declared_content_type: str | None,
        extension: str,
        detected_format: str | None,
        detected_content_type: str | None,
        size_bytes: int,
        width: int | None = None,
        height: int | None = None,
        image_mode: str | None = None,
    ) -> None:
        logger.warning(
            "Rejected document input: filename=%r declared_mime=%s "
            "extension=%s detected_format=%s detected_mime=%s "
            "size_bytes=%d width=%s height=%s image_mode=%s",
            cls._safe_filename(filename),
            declared_content_type,
            extension,
            detected_format,
            detected_content_type,
            size_bytes,
            width,
            height,
            image_mode,
        )

    @staticmethod
    def _safe_filename(filename: str) -> str:
        return Path(filename).name.replace("\r", " ").replace("\n", " ")[:255]

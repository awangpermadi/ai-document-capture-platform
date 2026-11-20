import argparse
import mimetypes
import os
import sys
from pathlib import Path

from pydantic import ValidationError

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _content_type_for(path: Path) -> str | None:
    content_type, _ = mimetypes.guess_type(path.name)
    if path.suffix.lower() in {".jpg", ".jpeg", ".jpe"}:
        return "image/jpeg"
    return content_type


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Directly test Azure Document Intelligence on one local file."
    )
    parser.add_argument("file_path", type=Path)
    arguments = parser.parse_args()
    file_path = arguments.file_path.resolve()

    if not file_path.is_file():
        print("input_error=File does not exist.")
        return 2

    content = file_path.read_bytes()
    content_type = _content_type_for(file_path)

    os.chdir(PROJECT_ROOT)
    sys.path.insert(0, str(PROJECT_ROOT))

    from app.config import get_settings
    from app.services.document_input import (
        DocumentInputError,
        DocumentValidator,
    )
    from app.services.document_intelligence import (
        AzureDocumentIntelligenceService,
        DocumentIntelligenceError,
    )

    try:
        settings = get_settings()
    except ValidationError:
        print("input_error=Azure settings are not configured.")
        return 2
    if not settings.azure_document_intelligence_endpoint or not (
        settings.azure_document_intelligence_key
    ):
        print("input_error=Azure settings are not configured.")
        return 2
    try:
        validated = DocumentValidator.validate(
            content,
            original_filename=file_path.name,
            declared_content_type=content_type,
        )
    except DocumentInputError as error:
        print(f"filename={file_path.name}")
        print(f"declared_mime={content_type}")
        print(f"detected_extension={file_path.suffix.lower()}")
        print(f"byte_size={len(content)}")
        print(f"detected_format={error.detected_format}")
        print(f"detected_content_type={error.detected_content_type}")
        print(f"image_width={error.width}")
        print(f"image_height={error.height}")
        print(f"image_mode={error.image_mode}")
        print(f"input_validation_error={error}")
        return 2

    print(f"filename={validated.original_filename}")
    print(f"declared_mime={validated.declared_content_type}")
    print(f"detected_extension={validated.extension}")
    print(f"detected_format={validated.detected_format}")
    print(f"detected_content_type={validated.detected_content_type}")
    print(f"byte_size={validated.size_bytes}")
    print(f"image_width={validated.width}")
    print(f"image_height={validated.height}")
    print(f"image_mode={validated.image_mode}")
    print(f"normalization_applied={validated.normalization_applied}")

    try:
        result = AzureDocumentIntelligenceService().analyze_document(validated)
    except DocumentIntelligenceError as error:
        azure_error = error.azure_exception
        print(
            "exception_class="
            + (
                type(azure_error).__name__
                if azure_error is not None
                else type(error).__name__
            )
        )
        print(
            "http_status="
            + str(getattr(azure_error, "status_code", None))
        )
        print(f"azure_error_code={error.azure_error_code}")
        print(f"azure_error_message={error.azure_error_message}")
        return 1

    print("azure_analysis=success")
    print(f"model_id={AzureDocumentIntelligenceService.MODEL_ID}")
    print(f"document_count={len(result.documents or [])}")
    print(f"page_count={len(result.pages or [])}")
    print(f"content_characters={len(result.content or '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

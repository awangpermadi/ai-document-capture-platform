from io import BytesIO

import pytest
from PIL import Image

from app.services.document_input import (
    DocumentInputError,
    DocumentValidator,
    MAX_FILE_SIZE,
    ValidatedDocument,
)


def image_bytes(
    image_format: str,
    *,
    mode: str = "RGB",
    exif_orientation: int | None = None,
) -> bytes:
    image = Image.new(mode, (40, 20), color=128)
    options: dict[str, object] = {}
    if exif_orientation is not None:
        exif = Image.Exif()
        exif[274] = exif_orientation
        options["exif"] = exif
    output = BytesIO()
    image.save(output, format=image_format, **options)
    return output.getvalue()


def validate(
    content: bytes,
    *,
    filename: str,
    content_type: str,
) -> ValidatedDocument:
    return DocumentValidator.validate(
        content,
        original_filename=filename,
        declared_content_type=content_type,
    )


def test_rgb_jpeg_is_accepted() -> None:
    content = image_bytes("JPEG")

    document = validate(
        content,
        filename="receipt.jpg",
        content_type="image/jpeg",
    )

    assert document.detected_format == "JPEG"
    assert document.detected_content_type == "image/jpeg"
    assert (document.width, document.height, document.image_mode) == (
        40,
        20,
        "RGB",
    )
    assert document.analysis_content == content


def test_jpeg_and_octet_stream_mime_are_accepted() -> None:
    content = image_bytes("JPEG")

    document = validate(
        content,
        filename="receipt.jpeg",
        content_type="image/jpeg",
    )
    octet_stream_document = validate(
        content,
        filename="receipt.jpg",
        content_type="application/octet-stream",
    )

    assert document.detected_content_type == "image/jpeg"
    assert octet_stream_document.detected_content_type == "image/jpeg"


def test_grayscale_jpeg_is_accepted_without_unnecessary_conversion() -> None:
    content = image_bytes("JPEG", mode="L")

    document = validate(
        content,
        filename="receipt.jpg",
        content_type="image/jpeg",
    )

    assert document.image_mode == "L"
    assert document.analysis_content == content
    assert document.normalization_applied is False


def test_valid_png_is_accepted() -> None:
    document = validate(
        image_bytes("PNG"),
        filename="receipt.png",
        content_type="image/png",
    )

    assert document.detected_format == "PNG"
    assert document.detected_content_type == "image/png"


def test_decoded_png_overrides_misleading_jpeg_mime_and_extension(
    caplog: pytest.LogCaptureFixture,
) -> None:
    document = validate(
        image_bytes("PNG"),
        filename="misleading.jpg",
        content_type="image/jpeg",
    )

    assert document.detected_format == "PNG"
    assert document.detected_content_type == "image/png"
    assert "declared_mime=image/jpeg" in caplog.text
    assert "detected_mime=image/png" in caplog.text


def test_supported_pdf_is_accepted_without_pillow() -> None:
    document = validate(
        b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF",
        filename="receipt.pdf",
        content_type="application/pdf",
    )

    assert document.detected_format == "PDF"
    assert document.detected_content_type == "application/pdf"
    assert document.width is None
    assert document.height is None
    assert document.image_mode is None


def test_jpeg_named_pdf_is_detected_as_jpeg() -> None:
    document = validate(
        image_bytes("JPEG"),
        filename="receipt.pdf",
        content_type="application/pdf",
    )

    assert document.detected_format == "JPEG"
    assert document.detected_content_type == "image/jpeg"


def test_corrupt_jpeg_and_arbitrary_text_are_rejected_with_422() -> None:
    for content in (
        b"\xff\xd8\xff" + b"not a decodable jpeg",
        b"arbitrary text",
    ):
        with pytest.raises(DocumentInputError) as error:
            validate(
                content,
                filename="receipt.jpg",
                content_type="image/jpeg",
            )
        assert error.value.status_code == 422


def test_fake_pdf_is_rejected_with_422() -> None:
    with pytest.raises(DocumentInputError) as error:
        validate(
            b"not a pdf",
            filename="receipt.pdf",
            content_type="application/pdf",
        )

    assert error.value.status_code == 422


def test_unsupported_gif_is_rejected_with_415() -> None:
    content = image_bytes("GIF")

    with pytest.raises(DocumentInputError) as error:
        validate(
            content,
            filename="receipt.jpg",
            content_type="image/jpeg",
        )

    assert error.value.status_code == 415
    assert error.value.detected_format == "GIF"


def test_webp_candidate_is_rejected_as_unsupported_not_mime_mismatch() -> None:
    content = image_bytes("WEBP")

    with pytest.raises(DocumentInputError) as error:
        validate(
            content,
            filename="receipt.jpg",
            content_type="image/jpeg",
        )

    assert error.value.status_code == 415
    assert error.value.detected_format == "WEBP"
    assert error.value.width == 40
    assert error.value.height == 20
    assert error.value.image_mode == "RGB"


def test_empty_document_is_rejected_with_400() -> None:
    with pytest.raises(DocumentInputError) as error:
        validate(b"", filename="receipt.jpg", content_type="image/jpeg")

    assert error.value.status_code == 400


def test_over_10mb_is_rejected_before_image_decoding() -> None:
    with pytest.raises(DocumentInputError) as error:
        validate(
            b"x" * (MAX_FILE_SIZE + 1),
            filename="receipt.jpg",
            content_type="image/jpeg",
        )

    assert error.value.status_code == 413


def test_exif_orientation_is_normalized_without_changing_original() -> None:
    original = image_bytes("JPEG", exif_orientation=6)

    document = validate(
        original,
        filename="receipt.jpg",
        content_type="image/jpeg",
    )

    assert document.normalization_applied is True
    assert document.original_content == original
    assert document.analysis_content != original
    with Image.open(BytesIO(document.analysis_content)) as normalized:
        assert normalized.format == "JPEG"
        assert normalized.size == (20, 40)


def test_problematic_png_mode_is_normalized_in_memory() -> None:
    original = image_bytes("PNG", mode="P")

    document = validate(
        original,
        filename="receipt.png",
        content_type="image/png",
    )

    assert document.normalization_applied is True
    assert document.original_content == original
    with Image.open(BytesIO(document.analysis_content)) as normalized:
        assert normalized.format == "PNG"
        assert normalized.mode == "RGB"


def test_decompression_bomb_warning_is_rejected_without_disabling_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)

    with pytest.raises(DocumentInputError) as error:
        validate(
            image_bytes("PNG"),
            filename="receipt.png",
            content_type="image/png",
        )

    assert error.value.status_code == 422

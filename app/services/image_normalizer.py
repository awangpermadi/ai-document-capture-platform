import warnings
from dataclasses import dataclass, field
from io import BytesIO

from PIL import Image, ImageOps


@dataclass(frozen=True)
class ImageNormalizationResult:
    content: bytes = field(repr=False)
    applied: bool


def normalize_image_for_analysis(
    content: bytes,
    *,
    detected_format: str,
) -> ImageNormalizationResult:
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(BytesIO(content)) as source:
            orientation = source.getexif().get(274, 1)
            source_mode = source.mode
            image = ImageOps.exif_transpose(source)

            if detected_format == "JPEG":
                supported_modes = {"L", "RGB"}
                target_mode = source_mode if source_mode in supported_modes else "RGB"
                output_format = "JPEG"
            else:
                supported_modes = {"L", "LA", "RGB", "RGBA"}
                target_mode = source_mode
                if source_mode not in supported_modes:
                    has_transparency = (
                        "A" in source_mode or "transparency" in source.info
                    )
                    target_mode = "RGBA" if has_transparency else "RGB"
                output_format = "PNG"

            normalized = (
                orientation != 1
                or source_mode != target_mode
            )
            if not normalized:
                return ImageNormalizationResult(
                    content=content,
                    applied=False,
                )

            if image.mode != target_mode:
                image = image.convert(target_mode)
            output = BytesIO()
            if output_format == "JPEG":
                image.save(output, format=output_format, quality=94)
            else:
                image.save(output, format=output_format)
            return ImageNormalizationResult(
                content=output.getvalue(),
                applied=True,
            )

"""Shrink a notebook's embedded images before they're written back.

A notebook executed with displayed photos (e.g. an error-analysis grid) can
carry tens of megabytes of RGBA PNG image outputs between runs. For a large
PNG that's actually a photo, re-encoding it as JPEG is far smaller for
little visible loss; a PNG that's a chart or line art stays a PNG (JPEG
would blur it), just re-saved with its own compression maximized.
"""

import base64
from io import BytesIO
from typing import Any

_PNG_MIME = "image/png"
_JPEG_MIME = "image/jpeg"


def _mime_text(data: dict[str, Any], mime: str) -> str:
    value = data.get(mime, "")
    return "".join(value) if isinstance(value, list) else value


def recompress_output_images(
    outputs: list[dict[str, Any]],
    *,
    max_image_kb: int = 200,
    jpeg_quality: int = 85,
) -> None:
    """Shrink large `image/png` outputs of `outputs`, in place.

    Each `image/png` output above `max_image_kb` is re-encoded as
    `image/jpeg` (RGB, alpha flattened on white, `jpeg_quality`) when that's
    at least twice smaller -- the common case for photos -- or re-saved as
    an optimized PNG otherwise -- the common case for charts and line art,
    which JPEG blurs. An output's `metadata` sizing hints (e.g. `width`/
    `height`) follow its data to the new mime type. Pillow is only imported,
    and only required, when at least one output needs recompressing.

    Args:
        outputs: A code cell's outputs, mutated in place.
        max_image_kb: Size, in KiB, above which a PNG output is considered \
            for recompression.
        jpeg_quality: JPEG quality used when an image is re-encoded.
    """
    threshold = max_image_kb * 1024
    targets: list[tuple[dict[str, Any], bytes]] = []
    for output in outputs:
        data = output.get("data")
        if not isinstance(data, dict) or _PNG_MIME not in data:
            continue
        raw = base64.b64decode(_mime_text(data, _PNG_MIME))
        if len(raw) > threshold:
            targets.append((output, raw))
    if not targets:
        return

    from ..extras import extras_imports

    with extras_imports("labs"):
        from PIL import Image

    for output, raw in targets:
        image = Image.open(BytesIO(raw))
        image.load()

        png_buffer = BytesIO()
        image.save(png_buffer, format="PNG", optimize=True)
        png_bytes = png_buffer.getvalue()

        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.split()[-1])
        jpeg_buffer = BytesIO()
        background.save(jpeg_buffer, format="JPEG", quality=jpeg_quality)
        jpeg_bytes = jpeg_buffer.getvalue()

        mime, encoded = (
            (_JPEG_MIME, jpeg_bytes)
            if len(jpeg_bytes) * 2 <= len(png_bytes)
            else (_PNG_MIME, png_bytes)
        )

        data = output["data"]
        del data[_PNG_MIME]
        data[mime] = base64.b64encode(encoded).decode("ascii")
        metadata = output.get("metadata")
        if isinstance(metadata, dict) and _PNG_MIME in metadata:
            metadata[mime] = metadata.pop(_PNG_MIME)

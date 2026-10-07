import base64
from io import BytesIO
from typing import Any

from PIL import Image, ImageDraw, ImageFilter

from deckz.labs.images import recompress_output_images


def _png_output(image: Image.Image, **metadata: Any) -> dict[str, Any]:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    data = base64.b64encode(buffer.getvalue()).decode("ascii")
    output: dict[str, Any] = {
        "output_type": "display_data",
        "data": {"image/png": data, "text/plain": ["<Figure>"]},
    }
    if metadata:
        output["metadata"] = {"image/png": metadata}
    return output


def _photo_like() -> Image.Image:
    # Blurred noise: smoothly-varying, non-repeating values, like a photo --
    # a worst case for PNG's DEFLATE backreferences, an easy case for JPEG.
    channels = [
        Image.effect_noise((300, 300), 40).filter(ImageFilter.GaussianBlur(6))
        for _ in range(3)
    ]
    return Image.merge("RGB", channels)


def _chart_like() -> Image.Image:
    # Flat background and a few solid lines: PNG compresses this very well,
    # and JPEG's block artifacts on the sharp edges don't pay for themselves.
    image = Image.new("RGB", (300, 300), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    for i in range(0, 300, 20):
        draw.line([(i, 0), (i, 300)], fill=(50, 50, 200), width=1)
    draw.line([(0, 0), (300, 300)], fill=(200, 50, 50), width=3)
    draw.line([(0, 300), (300, 0)], fill=(50, 200, 50), width=3)
    return image


def test_photo_like_image_becomes_jpeg() -> None:
    output = _png_output(_photo_like(), width=300, height=300)

    recompress_output_images([output], max_image_kb=1)

    assert "image/png" not in output["data"]
    assert "image/jpeg" in output["data"]
    assert "image/png" not in output["metadata"]
    assert output["metadata"]["image/jpeg"] == {"width": 300, "height": 300}


def test_chart_like_image_stays_png() -> None:
    output = _png_output(_chart_like(), width=300, height=300)

    recompress_output_images([output], max_image_kb=1)

    assert "image/jpeg" not in output["data"]
    assert "image/png" in output["data"]
    assert output["metadata"]["image/png"] == {"width": 300, "height": 300}
    # Re-saved with optimize=True: still a valid PNG.
    decoded = base64.b64decode(output["data"]["image/png"])
    Image.open(BytesIO(decoded)).load()


def test_image_below_threshold_is_untouched() -> None:
    tiny = Image.new("RGB", (2, 2), (255, 0, 0))
    output = _png_output(tiny)
    original_data = dict(output["data"])

    recompress_output_images([output], max_image_kb=200)

    assert output["data"] == original_data


def test_non_image_output_is_ignored() -> None:
    output = {"output_type": "stream", "name": "stdout", "text": ["hello\n"]}

    recompress_output_images([output], max_image_kb=1)

    assert output == {"output_type": "stream", "name": "stdout", "text": ["hello\n"]}


def test_handles_image_data_stored_as_list_of_chunks() -> None:
    buffer = BytesIO()
    _photo_like().save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    half = len(encoded) // 2
    output: dict[str, Any] = {
        "output_type": "display_data",
        "data": {"image/png": [encoded[:half], encoded[half:]]},
    }

    recompress_output_images([output], max_image_kb=1)

    assert "image/jpeg" in output["data"]

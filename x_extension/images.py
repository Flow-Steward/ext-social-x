"""Bounded local static image conversion, preserving the complete composition."""

from __future__ import annotations

import io
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

from .client import XError

INPUT_MAX_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 40_000_000
OUTPUT_MAX_BYTES = 5_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


def decode_static(body: bytes) -> Image.Image:
    if len(body) > INPUT_MAX_BYTES:
        raise XError("input_too_large", "Input image exceeds 20 MiB.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image = Image.open(io.BytesIO(body))
            if getattr(image, "n_frames", 1) != 1:
                raise XError(
                    "unsupported_image",
                    "A static image is required; animated images are unsupported.",
                )
            if image.width * image.height > MAX_PIXELS:
                raise XError("input_too_large", "Input image exceeds 40 million pixels.")
            if image.format not in {"JPEG", "PNG", "WEBP", "GIF"}:
                raise XError("unsupported_image", "Use a static JPEG, PNG, WEBP or GIF image.")
            image.load()
            return ImageOps.exif_transpose(image).convert("RGBA")
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        raise XError("invalid_image", "Image is invalid or exceeds the safe pixel limit.") from None


def prepare_image(body: bytes) -> bytes:
    image = decode_static(body)
    image.thumbnail((1200, 675), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (1200, 675), "white")
    canvas.paste(image, ((1200 - image.width) // 2, (675 - image.height) // 2), image)
    for quality in (92, 85, 75, 60):
        output = io.BytesIO()
        canvas.save(output, "JPEG", quality=quality, optimize=True)
        value = output.getvalue()
        if len(value) <= OUTPUT_MAX_BYTES:
            return value
    raise XError("image_too_large", "Prepared JPEG exceeds 5 MB; supply a simpler image.")


def validate_upload(body: bytes) -> None:
    if len(body) > OUTPUT_MAX_BYTES:
        raise XError("input_too_large", "X static media must be at most 5 MB.")
    decode_static(body)
    with Image.open(io.BytesIO(body)) as image:
        if image.format != "JPEG":
            raise XError(
                "unsupported_image", "Run prepare_image before uploading: static JPEG required."
            )

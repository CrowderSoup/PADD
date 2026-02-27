"""Utilities for normalising uploaded images to web-safe formats.

Any image format that browsers cannot display natively (HEIC, TIFF, BMP, …)
is converted to JPEG transparently before it is forwarded to the media
endpoint.  Callers receive a Django ``InMemoryUploadedFile`` that is
interchangeable with the original ``UploadedFile``.
"""

import io

from django.core.files.uploadedfile import InMemoryUploadedFile

# Images larger than this in either dimension are downscaled before JPEG
# encoding.  This caps RAM usage for large RAW/HEIC files (e.g. a 50 MP sensor
# image would otherwise hold ~150 MB of decoded pixels in memory).
_MAX_DIMENSION = 4096

# MIME types that every modern browser can display without any conversion.
_WEB_SAFE_MIME_TYPES = frozenset(
    {
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp",
        "image/avif",
        "image/svg+xml",
    }
)

# Extensions whose MIME type may be reported as something generic
# (e.g. "application/octet-stream") by some browsers or operating systems.
_NON_WEB_EXTENSIONS = frozenset(
    {
        ".heic",
        ".heif",
        ".tif",
        ".tiff",
        ".bmp",
        ".dng",
        ".cr2",
        ".nef",
        ".arw",
        ".raf",
        ".orf",
        ".rw2",
        ".pef",
    }
)


def _needs_conversion(uploaded_file) -> bool:
    if uploaded_file.content_type not in _WEB_SAFE_MIME_TYPES:
        return True
    name = (uploaded_file.name or "").lower()
    ext = ("." + name.rsplit(".", 1)[-1]) if "." in name else ""
    return ext in _NON_WEB_EXTENSIONS


def _to_jpeg(uploaded_file) -> InMemoryUploadedFile:
    """Convert *uploaded_file* to JPEG and return a new ``InMemoryUploadedFile``."""
    try:
        import pillow_heif  # registers HEIC/HEIF opener with Pillow

        pillow_heif.register_heif_opener()
    except ImportError:
        pass

    from PIL import Image, UnidentifiedImageError

    try:
        raw = Image.open(uploaded_file)
        raw.load()  # force-decode so format errors surface here
    except (UnidentifiedImageError, Exception) as exc:
        raise ValueError(f"Cannot decode image: {exc}") from exc

    if raw.mode not in ("RGB", "L"):
        img = raw.convert("RGB")
        raw.close()
    else:
        img = raw

    if max(img.size) > _MAX_DIMENSION:
        img.thumbnail((_MAX_DIMENSION, _MAX_DIMENSION), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    img.close()
    size = buf.tell()
    buf.seek(0)

    stem = uploaded_file.name.rsplit(".", 1)[0] if "." in uploaded_file.name else uploaded_file.name
    new_name = stem + ".jpg"

    return InMemoryUploadedFile(
        file=buf,
        field_name=None,
        name=new_name,
        content_type="image/jpeg",
        size=size,
        charset=None,
    )


def maybe_convert(uploaded_file):
    """Return *uploaded_file* converted to JPEG if it is not web-native.

    Files already in a web-safe format (JPEG, PNG, GIF, WebP, AVIF, SVG) are
    returned unchanged.  Raises ``ValueError`` if the image cannot be decoded.
    """
    if not _needs_conversion(uploaded_file):
        return uploaded_file
    return _to_jpeg(uploaded_file)

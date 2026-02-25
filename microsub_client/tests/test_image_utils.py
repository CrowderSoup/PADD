"""Tests for microsub_client.image_utils."""

import io
from unittest.mock import MagicMock, patch

from django.core.files.uploadedfile import InMemoryUploadedFile, SimpleUploadedFile
from django.test import TestCase

from microsub_client import image_utils


def _make_file(name, content_type, data=b"fake"):
    return SimpleUploadedFile(name, data, content_type=content_type)


def _real_image(fmt, mode="RGB"):
    """Return a minimal real image as an InMemoryUploadedFile."""
    from PIL import Image

    ext_map = {"JPEG": ".jpg", "PNG": ".png", "TIFF": ".tiff", "BMP": ".bmp"}
    buf = io.BytesIO()
    Image.new(mode, (4, 4), color=(100, 150, 200)).save(buf, format=fmt)
    size = buf.tell()
    buf.seek(0)
    mime_map = {"JPEG": "image/jpeg", "PNG": "image/png", "TIFF": "image/tiff", "BMP": "image/bmp"}
    return InMemoryUploadedFile(buf, None, "test" + ext_map[fmt], mime_map[fmt], size, None)


class NeedsConversionTests(TestCase):
    def test_jpeg_is_web_safe(self):
        self.assertFalse(image_utils._needs_conversion(_make_file("p.jpg", "image/jpeg")))

    def test_png_is_web_safe(self):
        self.assertFalse(image_utils._needs_conversion(_make_file("p.png", "image/png")))

    def test_webp_is_web_safe(self):
        self.assertFalse(image_utils._needs_conversion(_make_file("p.webp", "image/webp")))

    def test_gif_is_web_safe(self):
        self.assertFalse(image_utils._needs_conversion(_make_file("p.gif", "image/gif")))

    def test_avif_is_web_safe(self):
        self.assertFalse(image_utils._needs_conversion(_make_file("p.avif", "image/avif")))

    def test_heic_needs_conversion(self):
        self.assertTrue(image_utils._needs_conversion(_make_file("p.heic", "image/heic")))

    def test_heif_needs_conversion(self):
        self.assertTrue(image_utils._needs_conversion(_make_file("p.heif", "image/heif")))

    def test_tiff_needs_conversion(self):
        self.assertTrue(image_utils._needs_conversion(_make_file("p.tiff", "image/tiff")))

    def test_bmp_needs_conversion(self):
        self.assertTrue(image_utils._needs_conversion(_make_file("p.bmp", "image/bmp")))

    def test_heic_with_octet_stream_mime_needs_conversion(self):
        """iOS may report HEIC as application/octet-stream."""
        self.assertTrue(
            image_utils._needs_conversion(
                _make_file("photo.heic", "application/octet-stream")
            )
        )


class MaybeConvertTests(TestCase):
    def test_web_safe_file_returned_unchanged(self):
        f = _make_file("photo.jpg", "image/jpeg")
        result = image_utils.maybe_convert(f)
        self.assertIs(result, f)

    def test_non_web_safe_file_passes_to_to_jpeg(self):
        f = _make_file("photo.heic", "image/heic")
        converted = MagicMock()
        with patch("microsub_client.image_utils._to_jpeg", return_value=converted) as mock:
            result = image_utils.maybe_convert(f)
            mock.assert_called_once_with(f)
            self.assertIs(result, converted)

    def test_conversion_error_propagates_as_value_error(self):
        f = _make_file("photo.heic", "image/heic")
        with patch("microsub_client.image_utils._to_jpeg", side_effect=ValueError("bad image")):
            with self.assertRaises(ValueError, msg="bad image"):
                image_utils.maybe_convert(f)

    def test_real_tiff_converted_to_jpeg(self):
        f = _real_image("TIFF")
        result = image_utils.maybe_convert(f)
        self.assertIsInstance(result, InMemoryUploadedFile)
        self.assertEqual(result.content_type, "image/jpeg")
        self.assertEqual(result.name, "test.jpg")
        self.assertGreater(result.size, 0)

    def test_real_bmp_converted_to_jpeg(self):
        f = _real_image("BMP")
        result = image_utils.maybe_convert(f)
        self.assertEqual(result.content_type, "image/jpeg")
        self.assertEqual(result.name, "test.jpg")

    def test_real_jpeg_returned_unchanged(self):
        f = _real_image("JPEG")
        result = image_utils.maybe_convert(f)
        self.assertIs(result, f)

    def test_rgba_image_converted_without_error(self):
        """RGBA mode (e.g. PNG with transparency) is handled by converting to RGB."""
        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGBA", (4, 4), color=(0, 128, 255, 200)).save(buf, format="PNG")
        size = buf.tell()
        buf.seek(0)
        f = InMemoryUploadedFile(buf, None, "alpha.png", "image/tiff", size, None)
        # Treat it as needing conversion by spoofing a non-web MIME type
        f.content_type = "image/tiff"
        result = image_utils.maybe_convert(f)
        self.assertEqual(result.content_type, "image/jpeg")

    def test_unreadable_file_raises_value_error(self):
        f = _make_file("photo.tiff", "image/tiff", data=b"not-an-image")
        with self.assertRaises(ValueError):
            image_utils.maybe_convert(f)

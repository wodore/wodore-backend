"""Tests for Image.create_image_from_schema image-format handling.

The format is detected from the downloaded CONTENT, not the URL — a hut
page only needs to ship one BMP/GIF/TIFF photo to abort a whole hut
import run with ``ValueError: Unsupported image type``. Unsupported
formats are now skipped with a warning (same semantics as unidentified
content).
"""

import io

import pytest
from hut_services import AuthorSchema, LicenseSchema, PhotoSchema, SourceSchema
from PIL import Image as PILImage
from pydantic_string_url import HttpUrl

from server.apps.images.models import Image

pytestmark = pytest.mark.django_db


class _FakeResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def raise_for_status(self) -> None:
        return None


def _photo(url: str) -> PhotoSchema:
    return PhotoSchema(
        licenses=[LicenseSchema(slug="unknown", name="Unknown")],
        source=SourceSchema(name="test", url=HttpUrl("https://example.com")),
        author=AuthorSchema(name="test"),
        raw_url=HttpUrl(url),
        url=HttpUrl(url),
        width=1,
        height=1,
        capture_date=None,
    )


def _patch_download(monkeypatch: pytest.MonkeyPatch, content: bytes) -> None:
    def _fake_get(*args: object, **kwargs: object) -> _FakeResponse:
        return _FakeResponse(content)

    monkeypatch.setattr("server.apps.images.models.requests.get", _fake_get)


class TestCreateImageFromSchemaFormats:
    def test_bmp_content_is_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        buf = io.BytesIO()
        PILImage.new("RGB", (1, 1)).save(buf, format="BMP")
        _patch_download(monkeypatch, buf.getvalue())

        img = Image.create_image_from_schema(
            _photo("https://example.com/photo.bmp"),
            path="test",
            default_caption=None,
            tags=[],
        )
        assert img is None

    def test_gif_content_is_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        buf = io.BytesIO()
        PILImage.new("RGB", (1, 1)).save(buf, format="GIF")
        _patch_download(monkeypatch, buf.getvalue())

        img = Image.create_image_from_schema(
            _photo("https://example.com/photo.jpeg"),
            path="test",
            default_caption=None,
            tags=[],
        )
        assert img is None

    def test_jpeg_content_still_imports(self, monkeypatch: pytest.MonkeyPatch) -> None:
        buf = io.BytesIO()
        PILImage.new("RGB", (1, 1)).save(buf, format="JPEG")
        _patch_download(monkeypatch, buf.getvalue())

        img = Image.create_image_from_schema(
            _photo("https://example.com/photo.jpeg"),
            path="test",
            default_caption="Cap",
            tags=[],
        )
        assert img is not None
        assert img.image.name.endswith(".jpg")

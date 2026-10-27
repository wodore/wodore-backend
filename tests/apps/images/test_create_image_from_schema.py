"""Tests for `Image.create_image_from_schema` image-type handling.

Unsupported image formats served by upstream hut sources (BMP & friends)
must be skipped, not raise — one odd photo must not abort a whole hut
sync run (Sentry BACKEND-DJANGO-P).
"""

import io
from types import SimpleNamespace
from typing import Any

import pytest
from hut_services import PhotoSchema
from PIL import Image as PILImage

from server.apps.images.models import Image


def _photo(raw_url: str) -> PhotoSchema:
    """Minimal schema; no source → no dedupe DB query on the skip path."""
    return PhotoSchema(
        licenses=[],
        source=None,
        author=None,
        comment="",
        raw_url=raw_url,
        width=1,
        height=1,
        url="https://photos.example/hut",
        capture_date=None,
    )


def _no_sleep(_seconds: float) -> None:
    """Stand-in for the inter-request pause during tests."""


def _mock_download(
    monkeypatch: pytest.MonkeyPatch, content: bytes
) -> list[tuple[Any, ...]]:
    """Patch the raw-url download in place; record the calls made."""
    calls: list[tuple[Any, ...]] = []

    def fake_get(*args: Any, **kwargs: Any) -> Any:
        calls.append(args)
        return SimpleNamespace(content=content, raise_for_status=lambda: None)

    monkeypatch.setattr("server.apps.images.models.requests.get", fake_get)
    monkeypatch.setattr("server.apps.images.models.time.sleep", _no_sleep)
    return calls


def _encoded(format: str) -> bytes:
    buf = io.BytesIO()
    PILImage.new("RGB", (2, 2)).save(buf, format=format)
    return buf.getvalue()


@pytest.mark.parametrize("image_format", ["BMP", "GIF", "TIFF"])
def test_unsupported_image_type_is_skipped(
    monkeypatch: pytest.MonkeyPatch, image_format: str
) -> None:
    """A photo Pillow can decode but we do not serve is skipped (None)."""
    _mock_download(monkeypatch, _encoded(image_format))
    result = Image.create_image_from_schema(
        _photo(f"https://photos.example/hut.{image_format.lower()}")
    )
    assert result is None


def test_unidentified_content_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Payloads Pillow cannot decode at all stay on the existing skip path."""
    calls = _mock_download(monkeypatch, b"not an image at all")
    assert Image.create_image_from_schema(_photo("https://x.example/blob")) is None
    assert len(calls) == 1

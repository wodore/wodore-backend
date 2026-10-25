"""Tests for the refuges.info provider (JSON API implementation).

The provider queries ``/api/commentaires?id_point=`` (comments with dates,
captions, authors and photo references) and ``/api/point?id=`` (canonical
page URL) — no HTML scraping, no redirects (the HTML page 301s to its
canonical slug URL and httpx's raise_for_status treats that as an error,
which silently killed the old scraper). Photo URLs are built deterministically
from the comment id; the API's own ``photo-*`` fields are unreliable (often
the vignette, missing ``?`` before ``md=``) and are ignored.
"""

import asyncio
from datetime import timedelta
from typing import Any, override
from uuid import uuid4

import pytest

from django.core.cache.backends.locmem import LocMemCache

from server.apps.geometries.providers import refugesinfo as refugesinfo_module
from server.apps.geometries.providers.refugesinfo import API_BASE, RefugesInfoProvider
from server.apps.geometries.providers.schemas import GeoPlaceSchema, Source

API = "https://www.refuges.info"

CANONICAL_LIEN = f"{API}/point/3760/cabane-non-gardee/cabane-test/"


@pytest.fixture(autouse=True)
def _isolated_persistent_cache(monkeypatch: pytest.MonkeyPatch):
    """Locmem stand-in for the persistent cache (the provider caches the
    canonical point URL there — no database in these tests)."""
    cache = LocMemCache(f"test-refuges-{uuid4().hex}", {})
    monkeypatch.setattr(refugesinfo_module, "get_persistent_cache", lambda: cache)
    return cache


def _place() -> GeoPlaceSchema:
    return GeoPlaceSchema(
        slug="cabane-test",
        name="Cabane Test",
        name_i18n="Cabane Test",
        lat=44.13,
        lon=12.81,
        id=42,
        sources=[Source(slug="refuges", source_id="3760")],
    )


def _comment(comment_id: int, *, with_photo: bool = True) -> dict[str, Any]:
    comment = {
        "id_point": 3760,
        "id_commentaire": comment_id,
        "date_commentaire": "2026-08-16 18:14:02.018925+02",
        "texte_commentaire": "L&#039;abri est ouvert",
        "auteur_commentaire": "francois",
    }
    if with_photo:
        # The API's own fields are buggy (vignette path, missing '?') — the
        # provider must ignore them and build URLs from the id.
        comment["photo-vignette"] = (
            f"/photos_points/{comment_id}-vignette.jpegmd=071ded"
        )
        comment["photo-originale"] = (
            f"/photos_points/{comment_id}-vignette.jpegmd=071ded"
        )
    return comment


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, routes: dict[str, Any]):
        self.routes = routes
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    async def get(self, url: str, params: dict[str, Any] | None = None):
        self.calls.append((url, params))
        return _FakeResponse(self.routes[url])


def _routes(comments: dict[str, Any]) -> dict[str, Any]:
    return {
        f"{API}/api/commentaires": comments,
        f"{API}/api/point": {"features": [{"properties": {"lien": CANONICAL_LIEN}}]},
    }


def _point_calls(client: _FakeClient) -> int:
    return sum(1 for url, _params in client.calls if "/api/point" in url)


class TestFetchRefugesImages:
    def test_builds_results_from_comments(self):
        provider = RefugesInfoProvider()
        client = _FakeClient(
            _routes({"0": _comment(55824), "1": _comment(51137, with_photo=False)})
        )
        results = asyncio.run(provider._fetch_refuges_images(client, "3760", _place()))

        assert len(results) == 1  # the photo-less comment is skipped
        result = results[0]
        assert result.provider == "refuges"  # organization slug
        assert result.source_id == "C55824"  # stable across the old scraper's pins
        assert result.url_large == f"{API_BASE}/photos_points/55824-originale.jpeg"
        assert result.url_medium == f"{API_BASE}/photos_points/55824-reduite.jpeg"
        assert result.source_url == f"{CANONICAL_LIEN}#C55824"
        assert result.author == "francois"
        assert result.license_slug == "cc-by-sa-2.0-fr"
        # HTML entities in captions are unescaped.
        extra = result.extra or {}
        assert extra["caption"] == "L'abri est ouvert"

    def test_capture_date_is_timezone_aware(self):
        provider = RefugesInfoProvider()
        client = _FakeClient(_routes({"0": _comment(55824)}))
        results = asyncio.run(provider._fetch_refuges_images(client, "3760", _place()))
        captured = results[0].captured_at
        assert captured is not None
        assert captured.tzinfo is not None
        assert captured.utcoffset() == timedelta(hours=2)  # the site's +02 offset
        assert (captured.year, captured.month, captured.day) == (2026, 8, 16)

    def test_canonical_url_cached_across_fetches(self):
        provider = RefugesInfoProvider()
        client = _FakeClient(_routes({"0": _comment(55824)}))
        asyncio.run(provider._fetch_refuges_images(client, "3760", _place()))
        point_calls_after_first = _point_calls(client)

        results = asyncio.run(provider._fetch_refuges_images(client, "3760", _place()))
        # The lien is served from the persistent cache — no second /api/point call.
        assert _point_calls(client) == point_calls_after_first
        assert results[0].source_url == f"{CANONICAL_LIEN}#C55824"
        cache_key = provider._get_metadata_cache_key("point_lien:3760")
        assert (
            refugesinfo_module.get_persistent_cache().get(cache_key) == CANONICAL_LIEN
        )

    def test_canonical_url_fallback_when_point_api_fails(self):
        provider = RefugesInfoProvider()

        class _BrokenClient(_FakeClient):
            @override
            async def get(self, url: str, params: dict[str, Any] | None = None):
                if "/api/point" in url:
                    raise RuntimeError("boom")
                return _FakeResponse(self.routes[url])

        client = _BrokenClient(_routes({"0": _comment(55824)}))
        results = asyncio.run(provider._fetch_refuges_images(client, "3760", _place()))
        assert results[0].source_url == f"{API_BASE}/point/3760#C55824"


class TestParseCaptureDate:
    def test_parses_site_offset_format(self):
        parsed = RefugesInfoProvider()._parse_capture_date(
            "2026-08-16 18:14:02.018925+02", "3760"
        )
        assert parsed is not None
        assert parsed.utcoffset() == timedelta(hours=2)

    def test_naive_falls_back_to_utc(self):
        parsed = RefugesInfoProvider()._parse_capture_date(
            "2026-08-16 18:14:02", "3760"
        )
        assert parsed is not None
        assert parsed.tzinfo is not None

    def test_garbage_returns_none(self):
        assert RefugesInfoProvider()._parse_capture_date("not a date", "3760") is None
        assert RefugesInfoProvider()._parse_capture_date(None, "3760") is None

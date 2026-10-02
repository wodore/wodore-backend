"""HTTP-level tests for the place SEO surface (meta + Markdown)."""

import pytest

from server.apps.geometries.models import GeoPlace

pytestmark = [pytest.mark.django_db]


@pytest.fixture(autouse=True)
def _frontend_domain(settings):
    settings.FRONTEND_DOMAIN = "https://wodore.com"


class TestPlaceMeta:
    def test_meta_detail(self, seed_data, client):
        place = GeoPlace.objects.filter(
            is_active=True, is_public=True, name__gt=""
        ).first()
        assert place is not None
        response = client.get(f"/v1/geo/places/{place.slug}/meta")
        assert response.status_code == 200
        assert "public, max-age=" in response.headers["Cache-Control"]
        data = response.json()
        assert data["slug"] == place.slug
        assert data["name"] == place.name
        assert data["page_url"].startswith("https://wodore.com/")
        assert f"/{place.slug}" in data["page_url"]
        assert data["jsonld"]["@type"] == "Place"
        assert data["jsonld"]["name"] == place.name

    def test_meta_always_has_image(self, seed_data, client):
        """No photo -> static-map card from the generic endpoint."""
        place = GeoPlace.objects.filter(
            is_active=True, is_public=True, name__gt=""
        ).first()
        assert place is not None
        data = client.get(f"/v1/geo/places/{place.slug}/meta").json()
        assert data["image"]
        assert "map%2Fstatic" in data["image"]  # imagor-wrapped endpoint URL
        assert "effect%3Dspotlight" in data["image"]
        assert "marker_scale%3D0.8" in data["image"]
        assert "zoom%3D15" in data["image"]

    def test_meta_unknown_slug_is_404(self, seed_data, client):
        assert client.get("/v1/geo/places/does-not-exist/meta").status_code == 404

    def test_meta_hidden_place_is_404(self, seed_data, client):
        place = GeoPlace.objects.filter(is_active=True, is_public=True).first()
        assert place is not None
        place.is_public = False
        place.save()
        assert client.get(f"/v1/geo/places/{place.slug}/meta").status_code == 404


class TestPlaceMarkdown:
    def test_markdown_detail(self, seed_data, client):
        place = GeoPlace.objects.filter(
            is_active=True, is_public=True, name__gt=""
        ).first()
        assert place is not None
        response = client.get(f"/v1/geo/places/{place.slug}.md")
        assert response.status_code == 200
        assert response.headers["Content-Type"].startswith("text/markdown")
        body = response.content.decode()
        assert f"# {place.name}" in body
        assert "## Overview" in body
        assert "## Description" in body
        assert "Data: [Wodore]" in body

    def test_markdown_unknown_slug_is_404(self, seed_data, client):
        assert client.get("/v1/geo/places/does-not-exist.md").status_code == 404


class TestHutOgCardFallback:
    def test_hut_meta_image_falls_back_to_static_map(self, seed_data, client):
        """Huts without a photo get the static map card (map.png)."""
        from server.apps.huts.models import Hut, HutImageAssociation

        HutImageAssociation.objects.all().delete()
        hut = Hut.objects.filter(is_active=True, is_public=True).first()
        assert hut is not None
        data = client.get(f"/v1/huts/{hut.slug}/meta").json()
        assert data["image"]
        assert "map%2Fstatic" in data["image"]
        assert "effect%3Dspotlight" in data["image"]
        assert "marker_scale%3D0.8" in data["image"]
        assert "zoom%3D15" in data["image"]


class TestPlaceOgPinnedImage:
    """Place og:image source resolution (same regression as huts: pinned
    external images keep the file field empty, origin URL in
    ``source_url_raw``)."""

    @pytest.fixture(autouse=True)
    def _isolated_cache(self, monkeypatch):
        from uuid import uuid4

        from django.core.cache.backends.locmem import LocMemCache

        from server.apps.geometries import image_response_cache as irc

        cache = LocMemCache(f"test-{uuid4().hex}", {})
        monkeypatch.setattr(irc, "_cache", lambda: cache)

    def test_pinned_place_image_serves_from_source_url_raw(self, seed_data, client):
        from urllib.parse import quote

        from django.contrib.gis.geos import Point

        from server.apps.geometries.models import GeoPlaceImageAssociation
        from server.apps.geometries.pinning import pin_place_images
        from server.apps.geometries.providers.base import ImageResult

        place = GeoPlace.objects.filter(is_active=True).first()
        assert place is not None
        GeoPlaceImageAssociation.objects.filter(geo_place=place).delete()
        url = "https://upload.wikimedia.org/wikipedia/commons/place_1920.jpg"
        pin_place_images(
            place,
            [
                ImageResult(
                    provider="wikicommons",
                    source_id="File:Place.jpg",
                    source_url="https://commons.wikimedia.org/wiki/File:Place.jpg",
                    image_type="flat",
                    captured_at=None,
                    location=Point(7.5, 46.5),
                    distance_m=42.0,
                    license_slug="cc-by-sa-4-0",
                    attribution="Test Author, CC BY-SA",
                    author="Test Author",
                    author_url=None,
                    url_large=url,
                    width=1920,
                    height=1080,
                    score=32767,
                )
            ],
        )
        data = client.get(f"/v1/geo/places/{place.slug}/meta").json()
        assert data["image"]
        assert quote(url, safe="") in data["image"]
        assert not data["image"].endswith("/wd")


class TestCategoriesMarkdown:
    def test_categories_index(self, seed_data, client):
        response = client.get("/v1/categories/index.md")
        assert response.status_code == 200
        assert response.headers["Content-Type"].startswith("text/markdown")
        body = response.content.decode()
        assert body.startswith("# Wodore categories")
        assert "`" in body  # slugs

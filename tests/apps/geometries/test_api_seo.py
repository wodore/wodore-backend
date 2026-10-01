"""HTTP-level tests for the place SEO surface (meta + Markdown)."""

from urllib.parse import quote

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
        """No photo -> generated og card (brand background + name)."""
        place = GeoPlace.objects.filter(
            is_active=True, is_public=True, name__gt=""
        ).first()
        assert place is not None
        data = client.get(f"/v1/geo/places/{place.slug}/meta").json()
        assert data["image"]
        # Signed absolute imagor URL in prod; relative /unsafe/ path when
        # IMAGOR_URL is unset (test env) — either way the name is drawn.
        assert "text(" in data["image"]
        assert quote(place.name) in data["image"]

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
    def test_hut_meta_image_falls_back_to_generated_card(self, seed_data, client):
        """Huts without a photo get the generated card, not an empty image."""
        from server.apps.huts.models import Hut, HutImageAssociation

        HutImageAssociation.objects.all().delete()
        hut = Hut.objects.filter(is_active=True, is_public=True).first()
        assert hut is not None
        data = client.get(f"/v1/huts/{hut.slug}/meta").json()
        assert data["image"]
        # imagor text filter with the URL-encoded name
        assert "text(" in data["image"]


class TestCategoriesMarkdown:
    def test_categories_index(self, seed_data, client):
        response = client.get("/v1/categories/index.md")
        assert response.status_code == 200
        assert response.headers["Content-Type"].startswith("text/markdown")
        body = response.content.decode()
        assert body.startswith("# Wodore categories")
        assert "`" in body  # slugs

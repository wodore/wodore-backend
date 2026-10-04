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

    @pytest.fixture(autouse=True)
    def _isolated_cache(self, monkeypatch):
        from uuid import uuid4

        from django.core.cache.backends.locmem import LocMemCache

        from server.apps.geometries import image_response_cache as irc

        cache = LocMemCache(f"test-{uuid4().hex}", {})
        monkeypatch.setattr(irc, "_cache", lambda: cache)

    def test_meta_always_has_image(self, seed_data, client):
        """No photo -> the image service's static-map fallback feature
        (direct card URL, og dimensions, spotlight, marker)."""
        place = GeoPlace.objects.filter(
            is_active=True, is_public=True, name__gt=""
        ).first()
        assert place is not None
        data = client.get(f"/v1/geo/places/{place.slug}/meta").json()
        assert data["image"]
        assert "map%2Fstatic" in data["image"]
        assert "effect%3Dspotlight" in data["image"]
        assert "marker_scale%3D0.56" in data["image"]
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
    @pytest.fixture(autouse=True)
    def _isolated_cache(self, monkeypatch):
        from uuid import uuid4

        from django.core.cache.backends.locmem import LocMemCache

        from server.apps.geometries import image_response_cache as irc

        cache = LocMemCache(f"test-{uuid4().hex}", {})
        monkeypatch.setattr(irc, "_cache", lambda: cache)

    def test_hut_meta_image_falls_back_to_static_map(self, seed_data, client):
        """Huts without a photo get the image service's static-map
        fallback feature — its card URL is the og:image, as-is (direct
        URL, og dimensions, spotlight, marker)."""
        from server.apps.huts.models import Hut, HutImageAssociation

        HutImageAssociation.objects.all().delete()
        hut = Hut.objects.filter(is_active=True, is_public=True).first()
        assert hut is not None
        data = client.get(f"/v1/huts/{hut.slug}/meta").json()
        assert data["image"]
        assert "map%2Fstatic" in data["image"]
        assert "effect%3Dspotlight" in data["image"]
        assert "marker_scale%3D0.56" in data["image"]
        assert "zoom%3D15" in data["image"]
        assert "size%3D1200x630" in data["image"]


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

    def test_pinned_only_images_are_not_consulted(self, seed_data, client):
        """Pinned rows are the image service's business — the place og
        reads only the cached gallery response, so a pins-only place
        (no cached response) serves the static-map card."""
        from django.contrib.gis.geos import Point

        from server.apps.geometries.models import GeoPlaceImageAssociation
        from server.apps.geometries.pinning import pin_place_images
        from server.apps.geometries.providers.base import ImageResult

        place = GeoPlace.objects.filter(is_active=True).first()
        assert place is not None
        GeoPlaceImageAssociation.objects.filter(geo_place=place).delete()
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
                    url_large="https://upload.wikimedia.org/wikipedia/commons/place_1920.jpg",
                    width=1920,
                    height=1080,
                    score=32767,
                )
            ],
        )
        data = client.get(f"/v1/geo/places/{place.slug}/meta").json()
        assert data["image"]
        assert "map%2Fstatic" in data["image"]
        assert "effect%3Dspotlight" in data["image"]

    def test_gallery_top_image_beats_pins(self, seed_data, client):
        """The place og:image follows the gallery first: a cached
        images-for-place response wins over pinned rows (the same order
        as the hut meta endpoint)."""
        from urllib.parse import quote

        from django.contrib.gis.geos import Point

        from server.apps.geometries.models import GeoPlaceImageAssociation
        from server.apps.geometries.pinning import pin_place_images
        from server.apps.geometries.providers import post_process_images
        from server.apps.geometries.providers.base import ImageResult
        from server.apps.geometries.schemas import (
            ImageCollectionResponse,
            ImageMetadataSchema,
        )

        place = GeoPlace.objects.filter(is_active=True).first()
        assert place is not None
        GeoPlaceImageAssociation.objects.filter(geo_place=place).delete()
        pin_place_images(
            place,
            [
                ImageResult(
                    provider="wikicommons",
                    source_id="File:Pinned.jpg",
                    source_url="https://commons.wikimedia.org/wiki/File:Pinned.jpg",
                    image_type="flat",
                    captured_at=None,
                    location=Point(7.5, 46.5),
                    distance_m=0.0,
                    license_slug="cc-by-sa-4-0",
                    attribution="Pinned Author, CC BY-SA",
                    author="Pinned Author",
                    author_url=None,
                    url_large="https://upload.wikimedia.org/wikipedia/commons/pinned.jpg",
                    width=1920,
                    height=1080,
                    score=32767,
                )
            ],
        )
        # Warm the gallery cache exactly like the endpoint would (post-
        # processed camptocmp result under the gallery request shape).
        result = ImageResult(
            provider="camptocamp",
            source_id="c2c_place",
            source_url="https://www.camptocamp.org/images/1",
            image_type="flat",
            captured_at=None,
            location=Point(7.5, 46.5),
            distance_m=4.0,
            license_slug="cc-by-sa-3-0",
            attribution="Gallery Author, CC BY-SA",
            author="Gallery Author",
            author_url=None,
            url_large="https://media.camptocamp.org/c2corg-active/place_top.jpg",
            width=1920,
            height=1080,
            score=60,
        )
        from server.apps.geometries import image_response_cache as irc
        from server.apps.geometries.api_images import GALLERY_QUERY_SHAPE

        irc.set_response(
            irc.response_key("place", place.slug, lang="fr", **GALLERY_QUERY_SHAPE),
            ImageCollectionResponse(
                type="FeatureCollection",
                features=post_process_images([result]),
                metadata=ImageMetadataSchema(
                    total=1,
                    sources_queried=["camptocamp"],
                    query_radius_m=50,
                    center={"lat": 46.5, "lon": 7.5},
                    geoplaces_found=1,
                    huts_found=0,
                ),
            ),
        )
        data = client.get(f"/v1/geo/places/{place.slug}/meta").json()
        assert (
            quote("media.camptocamp.org/c2corg-active/place_top.jpg", safe="")
            in (data["image"])
        )
        assert "pinned.jpg" not in data["image"]


class TestCategoriesMarkdown:
    def test_categories_index_lists_sitemap_categories_with_counts(
        self, seed_data, client
    ):
        """Only seo_sitemap-include categories, with public place counts."""
        from server.apps.categories.models import Category

        # Roots default to exclude: the seed categories start hidden.
        peak = Category.objects.filter(slug="peak").first()
        assert peak is not None
        peak.seo_sitemap = "include"
        peak.save()
        try:
            public_places = GeoPlace.objects.filter(
                is_active=True, is_public=True, categories=peak
            ).count()
            assert public_places > 0

            response = client.get("/v1/categories/index.md")
            assert response.status_code == 200
            assert response.headers["Content-Type"].startswith("text/markdown")
            body = response.content.decode()
            assert body.startswith("# Wodore place categories")
            plural = "s" if public_places != 1 else ""
            assert f"`peak` ({public_places} place{plural})" in body
            # Categories without an effective include policy stay out.
            assert "`lake`" not in body
        finally:
            # Session-scoped seed DB: restore the default-exclude policy
            # so sitemap tests picking these places stay deterministic.
            peak.seo_sitemap = None
            peak.save()

    def test_categories_index_inherits_parent_policy(self, seed_data, client):
        """Children inherit the include policy from their parent."""
        from server.apps.categories.models import Category

        # Fresh categories (no seeded ones): mutating `accommodation`
        # would leak into sibling tests via the session-scoped seed DB.
        root = Category.objects.create(slug="seo-index-root", name="SEO Index Root")
        Category.objects.create(
            slug="seo-index-child", name="SEO Index Child", parent=root
        )
        root.seo_sitemap = "include"
        root.save()

        body = client.get("/v1/categories/index.md").content.decode()
        assert body.startswith("# Wodore place categories")
        # The child inherits "include" without its own flag.
        assert "- SEO Index Root `seo-index-root` (0 places)" in body
        assert "-   SEO Index Child `seo-index-child` (0 places)" in body

"""HTTP-level tests for the lean hut meta endpoint (/v1/huts/{slug}/meta)."""

import pytest

from server.apps.huts.models import Hut

pytestmark = [pytest.mark.django_db]


@pytest.fixture(autouse=True)
def _frontend_domain(settings):
    settings.FRONTEND_DOMAIN = "https://wodore.com"


class TestHutMeta:
    def test_meta_detail(self, seed_data, client):
        hut = Hut.objects.filter(is_active=True, is_public=True).first()
        assert hut is not None
        response = client.get(f"/v1/huts/{hut.slug}/meta")
        assert response.status_code == 200
        assert "public, max-age=" in response.headers["Cache-Control"]

        data = response.json()
        assert data["slug"] == hut.slug
        assert data["name"] == hut.name
        assert data["page_url"] == f"https://wodore.com/hut/{hut.slug}"
        assert data["lang"] == "en"  # settings.LANGUAGE_CODE
        # standard/reduced operation terminology (not open/closed season)
        assert "type_standard" in data
        assert "type_reduced" in data
        assert "capacity_standard" in data
        assert "capacity_reduced" in data
        assert "type_open" not in data
        assert "capacity_open" not in data
        # Ready-to-inline structured data.
        assert data["jsonld"]["@type"] == "LodgingBusiness"
        assert data["jsonld"]["url"] == data["page_url"]
        if hut.elevation:
            assert data["elevation"] == float(hut.elevation)
            assert data["jsonld"]["geo"]["latitude"] == pytest.approx(
                hut.location.y, abs=1e-5
            )

    def test_meta_title_is_name_dot_owner(self, seed_data, client):
        hut = Hut.objects.filter(is_active=True, is_public=True).first()
        assert hut is not None
        data = client.get(f"/v1/huts/{hut.slug}/meta").json()
        assert data["title"].startswith(hut.name)
        if hut.hut_owner and hut.hut_owner.name not in hut.name:
            assert "·" in data["title"]
            assert hut.hut_owner.name in data["title"]

    def test_meta_description_is_fact_sentences(self, seed_data, client):
        hut = Hut.objects.filter(is_active=True, is_public=True).first()
        assert hut is not None
        data = client.get(f"/v1/huts/{hut.slug}/meta").json()
        # Sentences end with a period, carry capacity/elevation when present.
        assert data["description"].endswith(".")
        if hut.capacity_open:
            assert str(hut.capacity_open) in data["description"]
            assert "places" in data["description"]  # English glue, default lang
        if hut.elevation:
            assert f"{int(hut.elevation)} m" in data["description"]

    def test_meta_description_localized(self, seed_data, client):
        hut = Hut.objects.filter(
            is_active=True, is_public=True, capacity_open__gt=0
        ).first()
        assert hut is not None
        default = client.get(f"/v1/huts/{hut.slug}/meta").json()["description"]
        de = client.get(f"/v1/huts/{hut.slug}/meta", {"lang": "de"}).json()[
            "description"
        ]
        fr = client.get(f"/v1/huts/{hut.slug}/meta", {"lang": "fr"}).json()[
            "description"
        ]
        it = client.get(f"/v1/huts/{hut.slug}/meta", {"lang": "it"}).json()[
            "description"
        ]
        assert "places" in default  # settings.LANGUAGE_CODE
        assert "Plätzen" in de
        assert "places" in fr
        assert "posti" in it

    def test_meta_description_closed_hut(self, seed_data, client):
        hut = Hut.objects.filter(
            is_active=True, is_public=True, hut_type_open__slug="closed"
        ).first()
        if hut is None:  # closed huts are rare in the seed — assert the guard
            assert "closed" not in Hut.objects.values_list(
                "hut_type_open__slug", flat=True
            )
            return
        data = client.get(f"/v1/huts/{hut.slug}/meta").json()
        assert data["description"].startswith("Currently closed.")

    def test_meta_lang_param_falls_back(self, seed_data, client):
        hut = Hut.objects.filter(is_active=True, is_public=True).first()
        assert hut is not None
        response = client.get(f"/v1/huts/{hut.slug}/meta", {"lang": "en"})
        assert response.status_code == 200
        assert response.json()["lang"] == "en"

    def test_meta_unknown_slug_is_404(self, seed_data, client):
        assert client.get("/v1/huts/does-not-exist-xyz/meta").status_code == 404

    def test_meta_hidden_hut_is_404(self, seed_data, client):
        hut = Hut.objects.filter(is_active=True, is_public=True).first()
        assert hut is not None
        hut.is_public = False
        hut.save()
        assert client.get(f"/v1/huts/{hut.slug}/meta").status_code == 404


class TestHutMetaOgSources:
    """og:image resolution: the top image of the images-by-hut response
    the frontend gallery renders — everything else (curated rows, the
    deprecated hut-services ``photos`` field) is the image service's
    business. The only fallback is the static-map card."""

    @pytest.fixture(autouse=True)
    def _isolated_cache(self, monkeypatch):
        from uuid import uuid4

        from django.core.cache.backends.locmem import LocMemCache

        from server.apps.geometries import image_response_cache as irc

        cache = LocMemCache(f"test-{uuid4().hex}", {})
        monkeypatch.setattr(irc, "_cache", lambda: cache)

    @pytest.fixture
    def hut(self, seed_data):
        hut = Hut.objects.filter(is_active=True, is_public=True).first()
        assert hut is not None
        return hut

    @staticmethod
    def _gallery_response(hut, top_raw: str):
        """ImageCollectionResponse built exactly like the endpoint: a
        camptocamp ImageResult through post_process_images."""
        from django.contrib.gis.geos import Point

        from server.apps.geometries.providers import post_process_images
        from server.apps.geometries.providers.base import ImageResult
        from server.apps.geometries.schemas import (
            ImageCollectionResponse,
            ImageMetadataSchema,
        )

        result = ImageResult(
            provider="camptocamp",
            source_id="c2c_120457",
            source_url="https://www.camptocamp.org/images/120457",
            image_type="flat",
            captured_at=None,
            location=Point(8.521, 46.7466),
            distance_m=4.0,
            license_slug="cc-by-sa-3-0",
            attribution="Test Author, CC BY-SA",
            author="Test Author",
            author_url=None,
            url_large=top_raw,
            width=1920,
            height=1080,
            score=60,
        )
        features = post_process_images([result])
        return ImageCollectionResponse(
            type="FeatureCollection",
            features=features,
            metadata=ImageMetadataSchema(
                total=len(features),
                sources_queried=["camptocamp"],
                query_radius_m=50,
                center={"lat": 46.7466, "lon": 8.521},
                geoplaces_found=0,
                huts_found=1,
            ),
        )

    @staticmethod
    def _warm_gallery_cache(hut, response, *, lang="en") -> None:
        from server.apps.geometries import image_response_cache as irc
        from server.apps.geometries.api_images import GALLERY_QUERY_SHAPE

        irc.set_response(
            irc.response_key("hut", hut.slug, lang=lang, **GALLERY_QUERY_SHAPE),
            response,
        )

    def test_gallery_top_image_is_og_image(self, hut, client):
        """The og:image is the top image of the cached images-by-hut
        response — the same photo the frontend gallery shows first."""
        from urllib.parse import quote

        self._warm_gallery_cache(
            hut,
            self._gallery_response(
                hut, "https://media.camptocamp.org/c2corg-active/1204579707.jpg"
            ),
        )
        data = client.get(f"/v1/huts/{hut.slug}/meta").json()
        assert (
            quote("media.camptocamp.org/c2corg-active/1204579707.jpg", safe="")
            in data["image"]
        )
        assert "/v1/geo/map/static" not in data["image"]
        # Wodore logo watermark: bottom, a bit left of center (0.33,
        # same position as the static-map cards).
        assert ",0.33,bottom-10,0)" in data["image"]

    def test_gallery_cached_in_other_language_is_used(self, hut, client):
        """The gallery is language-independent imagery — a response cached
        under any UI language serves the og lookup."""
        from urllib.parse import quote

        self._warm_gallery_cache(
            hut,
            self._gallery_response(hut, "https://media.camptocamp.org/anylang.jpg"),
            lang="fr",
        )
        data = client.get(f"/v1/huts/{hut.slug}/meta", {"lang": "de"}).json()
        assert quote("media.camptocamp.org/anylang.jpg", safe="") in data["image"]

    def test_deprecated_photos_field_is_ignored(self, hut, client):
        """hut.services `photos` is deprecated — it never becomes the
        og:image, warm gallery or not."""
        from urllib.parse import quote

        hut.photos = "https://static.suissealpine.sac-cas.ch/hero.jpg"
        hut.save(update_fields=["photos"])
        # Warm gallery wins even with the hero set …
        self._warm_gallery_cache(
            hut, self._gallery_response(hut, "https://media.camptocamp.org/top.jpg")
        )
        data = client.get(f"/v1/huts/{hut.slug}/meta").json()
        assert quote("media.camptocamp.org/top.jpg", safe="") in data["image"]
        assert "sac-cas.ch" not in data["image"]

    def test_cold_gallery_cache_uses_service_fallback(self, hut, client):
        """No cached gallery response (nobody opened the page yet) → the
        image service's static-map fallback feature — never the
        deprecated photos field."""
        hut.photos = "https://static.suissealpine.sac-cas.ch/hero.jpg"
        hut.save(update_fields=["photos"])
        data = client.get(f"/v1/huts/{hut.slug}/meta").json()
        assert data["image"]
        # imagor-composed map card: the map URL is the encoded source
        assert "map%2Fstatic" in data["image"]
        assert "effect%3Dspotlight" in data["image"]
        assert "marker_scale%3D0.8" in data["image"]
        assert "sac-cas.ch" not in data["image"]

    def test_fallback_feature_is_imagor_composed(self, hut, client):
        """A cached response whose only feature is the service's
        static-map fallback (is_fallback=true) goes through imagor
        (watermark composited, backend-served logo) — never raw."""
        from urllib.parse import quote

        from server.apps.geometries.api_images import _map_fallback_feature

        class _Req:
            def build_absolute_uri(self, uri: str) -> str:
                return f"https://wodore.com{uri}"

        feature = _map_fallback_feature(
            _Req(),
            slug=hut.slug,
            lat=46.5,
            lon=7.5,
            modified=hut.modified,
            place_type="hut",
        )
        from server.apps.geometries.schemas import (
            ImageCollectionResponse,
            ImageMetadataSchema,
        )

        self._warm_gallery_cache(
            hut,
            ImageCollectionResponse(
                type="FeatureCollection",
                features=[feature],
                metadata=ImageMetadataSchema(
                    total=1,
                    sources_queried=["wodore"],
                    query_radius_m=50,
                    center={"lat": 46.5, "lon": 7.5},
                    geoplaces_found=0,
                    huts_found=1,
                ),
            ),
        )
        data = client.get(f"/v1/huts/{hut.slug}/meta").json()
        # ... wrapped in imagor like every og image, never served raw
        assert not data["image"].startswith("https://wodore.com/v1/geo/map/static")
        assert quote("/v1/geo/map/static", safe="") in data["image"]
        assert "effect%3Dspotlight" in data["image"]

    def test_meta_does_not_disturb_other_hut_routes(self, seed_data, client):
        """/{slug} catch-all and the .md variant keep working alongside."""
        hut = Hut.objects.filter(is_active=True, is_public=True).first()
        assert hut is not None
        assert client.get(f"/v1/huts/{hut.slug}").status_code == 200
        assert client.get(f"/v1/huts/{hut.slug}.md").status_code == 200
        assert client.get(f"/v1/huts/{hut.slug}/meta").status_code == 200

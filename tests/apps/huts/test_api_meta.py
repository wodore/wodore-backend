"""HTTP-level tests for the lean hut meta endpoint (/v1/huts/{slug}/meta)."""

import pytest

from server.apps.huts.models import Hut, HutImageAssociation

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


class TestHutMetaOgImage:
    """og:image source resolution (regression: pinned external images).

    Pinned provider rows keep the file field empty and the origin URL in
    ``source_url_raw`` — the meta endpoint used to read only the file
    field, signing an empty path that resolved to the bare imagor media
    alias (``.../wd``) and 500-ing in imagor on staging."""

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
        HutImageAssociation.objects.filter(hut=hut).delete()
        # The provider hero (hut.photos) wins over everything — clear it
        # so the curated-image/fallback tests below stay meaningful.
        if hut.photos:
            hut.photos = ""
            hut.save(update_fields=["photos"])
        return hut

    @staticmethod
    def _pin(hut, *, source_id: str, score: int, url_large: str = ""):
        from django.contrib.gis.geos import Point

        from server.apps.geometries.pinning import pin_place_images
        from server.apps.geometries.providers.base import ImageResult

        return pin_place_images(
            hut,
            [
                ImageResult(
                    provider="wikicommons",
                    source_id=source_id,
                    source_url=f"https://commons.wikimedia.org/wiki/{source_id}",
                    image_type="flat",
                    captured_at=None,
                    location=Point(7.5, 46.5),
                    distance_m=42.0,
                    license_slug="cc-by-sa-4-0",
                    attribution="Test Author, CC BY-SA",
                    author="Test Author",
                    author_url=None,
                    url_large=url_large
                    or f"https://upload.wikimedia.org/wikipedia/commons/{source_id}.jpg",
                    width=1920,
                    height=1080,
                    score=score,
                )
            ],
        )

    def test_pinned_external_image_serves_from_source_url_raw(self, hut, client):
        """The og:image embeds the pinned origin URL, not the media alias."""
        from urllib.parse import quote

        url = "https://upload.wikimedia.org/wikipedia/commons/pinned_1920.jpg"
        self._pin(hut, source_id="File:Pinned.jpg", score=32767, url_large=url)
        data = client.get(f"/v1/huts/{hut.slug}/meta").json()
        assert data["image"]
        assert quote(url, safe="") in data["image"]
        # Never the bare imagor media alias (the staging bug: '.../wd').
        assert not data["image"].endswith("/wd")

    def test_local_file_image_keeps_working(self, hut, client):
        """Images with a local file still resolve through MEDIA_URL."""
        from urllib.parse import quote

        self._pin(hut, source_id="File:Pinned.jpg", score=32767)
        association = (
            HutImageAssociation.objects.filter(hut=hut).select_related("image").get()
        )
        image = association.image
        image.image = "images/local.jpg"
        image.save(update_fields=["image"])
        data = client.get(f"/v1/huts/{hut.slug}/meta").json()
        assert quote("images/local.jpg", safe="") in data["image"]

    def test_degenerate_pinned_row_falls_back_to_map_card(self, hut, client):
        """No file and no raw URL → static-map card, never a signed
        empty path."""
        self._pin(hut, source_id="File:Degenerate.jpg", score=32767)
        association = (
            HutImageAssociation.objects.filter(hut=hut).select_related("image").get()
        )
        association.image.source_url_raw = ""
        association.image.save(update_fields=["source_url_raw"])
        data = client.get(f"/v1/huts/{hut.slug}/meta").json()
        assert data["image"]
        assert "map%2Fstatic" in data["image"]
        # spotlight preview look, smaller marker (owner-approved)
        assert "effect%3Dspotlight" in data["image"]
        assert "marker_scale%3D0.8" in data["image"]
        assert "zoom%3D15" in data["image"]

    def test_hidden_top_image_is_skipped(self, hut, client):
        """An inactive top-scored image must not become the og:image —
        the next servable row (or the fallback) is used instead."""
        from urllib.parse import quote

        self._pin(
            hut,
            source_id="File:Hidden.jpg",
            score=32767,
            url_large="https://upload.wikimedia.org/wikipedia/commons/hidden.jpg",
        )
        self._pin(
            hut,
            source_id="File:Visible.jpg",
            score=100,
            url_large="https://upload.wikimedia.org/wikipedia/commons/visible.jpg",
        )
        top = (
            HutImageAssociation.objects.filter(hut=hut)
            .select_related("image")
            .order_by("-score")
            .first()
        )
        top.image.is_active = False
        top.image.save(update_fields=["is_active"])
        data = client.get(f"/v1/huts/{hut.slug}/meta").json()
        assert (
            quote("https://upload.wikimedia.org/wikipedia/commons/visible.jpg", safe="")
            in data["image"]
        )

    def test_meta_does_not_disturb_other_hut_routes(self, seed_data, client):
        """/{slug} catch-all and the .md variant keep working alongside."""
        hut = Hut.objects.filter(is_active=True, is_public=True).first()
        assert hut is not None
        assert client.get(f"/v1/huts/{hut.slug}").status_code == 200
        assert client.get(f"/v1/huts/{hut.slug}.md").status_code == 200
        assert client.get(f"/v1/huts/{hut.slug}/meta").status_code == 200


class TestHutMetaOgProviderHero:
    """og:image from the provider hero photo (hut-services ``photos``).

    Huts whose only photo comes from the provider sync (e.g. the SAC
    photo pinned into ``hut.photos``) used to fall through to the
    static-map card even though the detail endpoint shows that photo as
    the gallery hero and avatar — the preview must match the page."""

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
        HutImageAssociation.objects.filter(hut=hut).delete()
        hut.photos = ""
        hut.save(update_fields=["photos"])
        return hut

    def test_provider_hero_external_url_is_og_image(self, hut, client):
        """An external provider photo (e.g. SAC) becomes the og:image."""
        from urllib.parse import quote

        hut.photos = "https://static.suissealpine.sac-cas.ch/sewen.jpg"
        hut.save(update_fields=["photos"])
        data = client.get(f"/v1/huts/{hut.slug}/meta").json()
        assert data["image"]
        assert (
            quote("static.suissealpine.sac-cas.ch/sewen.jpg", safe="") in data["image"]
        )
        # Photo variant, not a map/brand card.
        assert "map%2Fstatic" not in data["image"]
        assert "meta.jpg" not in data["image"]

    def test_provider_hero_media_path_gets_media_prefix(self, hut, client):
        """A media-relative hero path resolves through MEDIA_URL."""
        from urllib.parse import quote

        hut.photos = "hut_photos/hero.jpg"
        hut.save(update_fields=["photos"])
        data = client.get(f"/v1/huts/{hut.slug}/meta").json()
        assert quote("hut_photos/hero.jpg", safe="") in data["image"]

    def test_provider_hero_wins_over_curated_images(self, hut, client):
        """The hero matches the page (avatar/gallery lead) even when
        curated, approved images exist."""
        from urllib.parse import quote

        TestHutMetaOgImage._pin(
            hut,
            source_id="File:Curated.jpg",
            score=32767,
            url_large="https://upload.wikimedia.org/wikipedia/commons/curated.jpg",
        )
        hut.photos = "https://static.suissealpine.sac-cas.ch/hero.jpg"
        hut.save(update_fields=["photos"])
        data = client.get(f"/v1/huts/{hut.slug}/meta").json()
        assert (
            quote("static.suissealpine.sac-cas.ch/hero.jpg", safe="") in data["image"]
        )
        assert "curated.jpg" not in data["image"]

    def test_no_hero_no_images_is_map_card(self, hut, client):
        """Without hero and curated images the map card stays."""
        data = client.get(f"/v1/huts/{hut.slug}/meta").json()
        assert data["image"]
        assert "map%2Fstatic" in data["image"]

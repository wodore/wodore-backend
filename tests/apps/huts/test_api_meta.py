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
        assert data["lang"] == "de"
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
            assert "Plätzen" in data["description"]  # German glue, default lang
        if hut.elevation:
            assert f"{int(hut.elevation)} m" in data["description"]

    def test_meta_description_localized(self, seed_data, client):
        hut = Hut.objects.filter(
            is_active=True, is_public=True, capacity_open__gt=0
        ).first()
        assert hut is not None
        de = client.get(f"/v1/huts/{hut.slug}/meta").json()["description"]
        en = client.get(f"/v1/huts/{hut.slug}/meta", {"lang": "en"}).json()[
            "description"
        ]
        fr = client.get(f"/v1/huts/{hut.slug}/meta", {"lang": "fr"}).json()[
            "description"
        ]
        it = client.get(f"/v1/huts/{hut.slug}/meta", {"lang": "it"}).json()[
            "description"
        ]
        assert "Plätzen" in de
        assert "places" in en
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
        assert data["description"].startswith("Derzeit geschlossen.")

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

    def test_meta_does_not_disturb_other_hut_routes(self, seed_data, client):
        """/{slug} catch-all and the .md variant keep working alongside."""
        hut = Hut.objects.filter(is_active=True, is_public=True).first()
        assert hut is not None
        assert client.get(f"/v1/huts/{hut.slug}").status_code == 200
        assert client.get(f"/v1/huts/{hut.slug}.md").status_code == 200
        assert client.get(f"/v1/huts/{hut.slug}/meta").status_code == 200

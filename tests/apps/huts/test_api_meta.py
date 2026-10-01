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

    def test_meta_description_contains_name(self, seed_data, client):
        hut = Hut.objects.filter(is_active=True, is_public=True).first()
        assert hut is not None
        data = client.get(f"/v1/huts/{hut.slug}/meta").json()
        assert hut.name in data["description"]

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

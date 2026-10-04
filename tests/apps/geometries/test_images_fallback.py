"""Tests for the static-map fallback feature in the image APIs."""

import pytest

from server.apps.geometries.models import GeoPlace
from server.apps.huts.models import Hut, HutImageAssociation

pytestmark = [pytest.mark.django_db]


@pytest.fixture(autouse=True)
def _no_images(db):
    HutImageAssociation.objects.all().delete()
    from server.apps.geometries.models import GeoPlaceImageAssociation

    GeoPlaceImageAssociation.objects.all().delete()


class TestImageFallback:
    """static_map_fallback defaults to true — every hut/place response
    carries at least the generated static-map card; false opts out."""

    def test_hut_without_images_default_includes_fallback(self, seed_data, client):
        hut = Hut.objects.filter(
            is_active=True, is_public=True, location__isnull=False
        ).first()
        assert hut is not None
        response = client.get(f"/v1/geo/images/hut/{hut.slug}", {"sources": "wodore"})
        assert response.status_code == 200
        data = response.json()
        features = data["features"]
        assert len(features) >= 1
        fallback_features = [f for f in features if f["properties"]["is_fallback"]]
        assert fallback_features, "expected the static-map fallback feature"
        props = fallback_features[0]["properties"]
        assert props["provider"]["slug"] == "wodore-map"
        assert "/v1/geo/map/static" in props["urls"]["landscape"]["md"]
        assert props["urls"]["landscape"]["md"].startswith("http")
        # og-style generation: spotlight effect, marker scale, zoom 15
        assert "effect=spotlight" in props["urls"]["landscape"]["md"]
        assert "marker_scale=0.5" in props["urls"]["landscape"]["md"]
        assert "zoom=15" in props["urls"]["landscape"]["md"]

    def test_hut_without_images_opt_out(self, seed_data, client):
        hut = Hut.objects.filter(
            is_active=True, is_public=True, location__isnull=False
        ).first()
        assert hut is not None
        response = client.get(
            f"/v1/geo/images/hut/{hut.slug}",
            {"sources": "wodore", "static_map_fallback": "false"},
        )
        assert response.status_code == 200
        features = response.json()["features"]
        assert not [f for f in features if f["properties"].get("is_fallback")]

    def test_place_without_images_default_fallback(self, seed_data, client):
        place = GeoPlace.objects.filter(
            is_active=True, is_public=True, location__isnull=False
        ).first()
        assert place is not None
        response = client.get(
            f"/v1/geo/images/place/{place.slug}", {"sources": "wodore"}
        )
        assert response.status_code == 200
        features = response.json()["features"]
        fallback_features = [f for f in features if f["properties"]["is_fallback"]]
        assert fallback_features
        assert (
            fallback_features[0]["properties"]["source_id"]
            == f"static-map:{place.slug}"
        )

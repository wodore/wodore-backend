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
    def test_hut_without_images_fallback_true(self, seed_data, client):
        hut = Hut.objects.filter(
            is_active=True, is_public=True, location__isnull=False
        ).first()
        assert hut is not None
        response = client.get(
            f"/v1/geo/images/hut/{hut.slug}", {"sources": "wodore", "fallback": "true"}
        )
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

    def test_hut_without_images_fallback_false_default(self, seed_data, client):
        hut = Hut.objects.filter(
            is_active=True, is_public=True, location__isnull=False
        ).first()
        assert hut is not None
        response = client.get(f"/v1/geo/images/hut/{hut.slug}", {"sources": "wodore"})
        assert response.status_code == 200
        features = response.json()["features"]
        assert not [f for f in features if f["properties"].get("is_fallback")]

    def test_place_without_images_fallback(self, seed_data, client):
        place = GeoPlace.objects.filter(
            is_active=True, is_public=True, location__isnull=False
        ).first()
        assert place is not None
        response = client.get(
            f"/v1/geo/images/place/{place.slug}",
            {"sources": "wodore", "fallback": "true"},
        )
        assert response.status_code == 200
        features = response.json()["features"]
        fallback_features = [f for f in features if f["properties"]["is_fallback"]]
        assert fallback_features
        assert (
            fallback_features[0]["properties"]["source_id"]
            == f"static-map:{place.slug}"
        )

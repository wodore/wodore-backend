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
        md = props["urls"]["landscape"]["md"]
        # Same pipeline as provider photos: signed imagor variants with
        # the identical size presets, the map render as encoded source.
        assert "v1%2Fgeo%2Fmap%2Fstatic" in md
        assert "/945x630/" in md  # landscape md preset, constrained to source
        assert "quality(85)" in md
        assert "effect%3Dspotlight" in md
        assert "marker_scale%3D0.56" in md
        assert "zoom%3D15" in md
        # square variants come from the square map render
        assert "size%3D1000x1000" in props["urls"]["square"]["md"]
        # original.raw stays the direct endpoint URL (og composes it)
        assert "/v1/geo/map/static" in props["urls"]["original"]["raw"]

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

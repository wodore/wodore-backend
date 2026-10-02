"""HTTP-level tests for the shared bbox viewport filter (BboxQuery).

Endpoints with spatial result sets accept ``bbox=minLon,minLat,maxLon,
maxLat``; the ``nearby`` endpoints deliberately keep center+radius (they
add distance ordering). The ETag-cached hut endpoints must fold the bbox
into their cache key — different boxes may not share an ETag.
"""

import datetime

import pytest

from django.contrib.gis.geos import Point
from django.utils import timezone

from server.apps.api.query import bbox_polygon
from server.apps.availability.models import HutAvailability
from server.apps.huts.models import Hut
from server.apps.organizations.models import Organization

pytestmark = [pytest.mark.django_db]

# Seed clusters: 4 huts east of lon 8.9, 6 huts west of lon 8.1
# (see tests/seed/huts.yaml).
EAST_BBOX = "8.9,46.0,10.0,47.0"
WEST_BBOX = "7.0,45.5,8.1,46.9"


class TestBboxPolygon:
    def test_none_when_unset(self):
        assert bbox_polygon(None) is None
        assert bbox_polygon("") is None

    def test_polygon_from_valid_bbox(self):
        polygon = bbox_polygon("7.0,45.5,8.0,46.5")
        assert polygon is not None
        assert polygon.srid == 4326
        assert polygon.contains(Point(7.5, 46.0, srid=4326))
        assert not polygon.contains(Point(9.0, 46.0, srid=4326))


class TestBboxValidation:
    def test_invalid_bbox_is_rejected(self, seed_data, client):
        invalid = [
            "7.0",  # too few values
            "7.0,45.5,8.0",  # too few values
            "7.0,45.5,8.0,46.5,9.0",  # too many values
            "a,b,c,d",  # not numbers
            "8.0,45.5,7.0,46.5",  # minLon > maxLon
            "7.0,46.5,8.0,45.5",  # minLat > maxLat
            "181,45.0,182,46.0",  # longitude out of range
            "7.0,-91,8.0,-90.5",  # latitude out of range
        ]
        for bad in invalid:
            response = client.get("/v1/huts/huts.geojson", {"bbox": bad})
            assert response.status_code == 400, bad

    def test_validation_applies_to_place_search_too(self, seed_data, client):
        response = client.get(
            "/v1/geo/places/search", {"q": "Dammastock", "bbox": "1,2,3"}
        )
        assert response.status_code == 400


class TestHutsGeojsonBbox:
    def test_bbox_filters_features(self, seed_data, client):
        full = client.get("/v1/huts/huts.geojson").json()
        east = client.get("/v1/huts/huts.geojson", {"bbox": EAST_BBOX}).json()
        west = client.get("/v1/huts/huts.geojson", {"bbox": WEST_BBOX}).json()
        assert len(full["features"]) == 10
        assert len(east["features"]) == 4
        assert len(west["features"]) == 6

    def test_etag_varies_with_bbox(self, seed_data, client):
        east = client.get("/v1/huts/huts.geojson", {"bbox": EAST_BBOX})
        west = client.get("/v1/huts/huts.geojson", {"bbox": WEST_BBOX})
        assert east.headers["ETag"]
        assert east.headers["ETag"] != west.headers["ETag"]

    def test_etag_stable_for_same_bbox(self, seed_data, client):
        first = client.get("/v1/huts/huts.geojson", {"bbox": EAST_BBOX})
        second = client.get("/v1/huts/huts.geojson", {"bbox": EAST_BBOX})
        assert first.headers["ETag"] == second.headers["ETag"]


class TestHutsListBbox:
    def test_bbox_filters_list(self, seed_data, client):
        full = client.get("/v1/huts/huts").json()
        east = client.get("/v1/huts/huts", {"bbox": EAST_BBOX}).json()
        assert len(full) == 10
        assert len(east) == 4


class TestHutSearchBbox:
    def test_bbox_narrows_name_search(self, seed_data, client):
        full = client.get("/v1/huts/search", {"q": "Testhütte"}).json()
        east = client.get(
            "/v1/huts/search", {"q": "Testhütte", "bbox": EAST_BBOX}
        ).json()
        assert len(full) == 10
        assert len(east) == 4


class TestAvailabilityGeojsonBbox:
    def test_bbox_filters_availability(self, seed_data, client):
        org = Organization.objects.first()
        assert org is not None
        east_hut = next(h for h in Hut.objects.all() if h.location.x >= 8.9)
        west_hut = next(h for h in Hut.objects.all() if h.location.x <= 8.1)
        assert east_hut is not None and west_hut is not None

        now = timezone.now()
        for hut in (east_hut, west_hut):
            HutAvailability.objects.create(
                hut=hut,
                availability_date=datetime.date(2027, 7, 1),
                first_checked=now,
                last_checked=now,
                source_organization=org,
                source_id="123",
                free=10,
                total=50,
                free_tolerance=0,
                occupancy_percent=80.0,
                occupancy_steps=80,
                occupancy_status="high",
                reservation_status="possible",
            )

        response = client.get(
            "/v1/huts/availability/2027-07-01.geojson", {"bbox": EAST_BBOX}
        )
        assert response.status_code == 200
        body = response.content.decode()
        assert east_hut.slug in body
        assert west_hut.slug not in body


class TestPlacesSearchBbox:
    def test_bbox_includes_matching_place(self, seed_data, client):
        # Tight box around the Dammastock seed peak (8.45, 46.6333).
        # lang=de: seeds carry no i18n names, the similarity degrades
        # below the default threshold for non-default languages.
        results = client.get(
            "/v1/geo/places/search",
            {"q": "Dammastock", "lang": "de", "bbox": "8.44,46.62,8.46,46.64"},
        ).json()
        # Reused local test DBs may accumulate duplicate seed rows
        # (the seed-hash cache key expires) — assert the box keeps only
        # Dammastock copies, which is what the filter promises.
        assert results
        assert {r["name"] for r in results} == {"Test Peak Dammastock"}

    def test_bbox_excluding_place_empties_results(self, seed_data, client):
        results = client.get(
            "/v1/geo/places/search",
            {"q": "Dammastock", "lang": "de", "bbox": WEST_BBOX},
        ).json()
        assert results == []

    def test_nearby_keeps_center_radius_semantics(self, seed_data, client):
        """No bbox on nearby: the unknown parameter is ignored."""
        response = client.get(
            "/v1/geo/places/nearby",
            {"lat": 46.6333, "lon": 8.45, "radius": 5000, "bbox": "0,0,1,1"},
        )
        assert response.status_code == 200
        results = response.json()
        assert any(r["name"] == "Test Peak Dammastock" for r in results)

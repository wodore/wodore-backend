"""Query-count pins for the cold endpoints (OpenSpec phase 3.4).

The nplusone replacement: each converted endpoint's query count is part
of its contract. Counts are measured COLD — the category endpoints page-
cache, so the cache is cleared first (the pin covers the cache-miss path
that fires once per hour in production).
"""

import pytest

from django.core.cache import cache
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

SYMBOLS_LIST_PIN = 1
CATEGORIES_COLD_PIN = 1
AVAILABILITY_CURRENT_PIN = 3  # hut fetch (types joined) + rows + association
AVAILABILITY_TREND_PIN = 2  # hut fetch + history rows
AVAILABILITY_GEOJSON_PIN = 1  # the SQL aggregate


@pytest.mark.django_db
class TestSymbolsQueryCount:
    def test_list_single_query(self):
        client = Client()
        with CaptureQueriesContext(connection) as ctx:
            response = client.get("/v1/symbols/?lang=de")
        assert response.status_code == 200
        assert len(ctx) == SYMBOLS_LIST_PIN, (
            f"get_symbols issued {len(ctx)} queries "
            f"(pin: {SYMBOLS_LIST_PIN}) — relation loading is schema-derived; "
            "scalar-typed FK fields must not lazy-load under from_attributes."
        )


@pytest.mark.django_db
class TestCategoriesQueryCount:
    """The tree build cost 9000 queries before the in-memory rewrite."""

    @pytest.mark.parametrize(
        ("url",),
        [
            ("/v1/categories/tree/root",),
            ("/v1/categories/list/root",),
            ("/v1/categories/map/root",),
        ],
    )
    def test_cold_build_single_query(self, url):
        cache.clear()  # page cache: pin the cache-miss path
        client = Client()
        with CaptureQueriesContext(connection) as ctx:
            response = client.get(url)
        assert response.status_code == 200
        assert len(ctx) == CATEGORIES_COLD_PIN, (
            f"{url} issued {len(ctx)} queries cold "
            f"(pin: {CATEGORIES_COLD_PIN}) — the whole tree loads in one "
            "query; a regression here is a traversal N+1."
        )

    def test_warm_hit_is_free(self):
        client = Client()
        client.get("/v1/categories/tree/root")
        with CaptureQueriesContext(connection) as ctx:
            response = client.get("/v1/categories/tree/root")
        assert response.status_code == 200
        assert len(ctx) == 0, "warm page-cache hits must not touch the database"


@pytest.fixture()
def availability_hut(db):
    """A public hut with type FKs set, availability rows, and one history entry."""
    import datetime

    from tests.factories.availability import AvailabilityFactory

    from server.apps.availability.models import HutAvailabilityHistory

    availability = AvailabilityFactory(free=3, total=10)
    hut = availability.hut
    # Trend filters first_checked__lte target-midnight; a "now()" stamp
    # would fall outside the window and 404.
    day_start = timezone.make_aware(
        datetime.datetime.combine(availability.availability_date, datetime.time.min)
    )
    HutAvailabilityHistory.objects.create(
        hut=hut,
        availability=availability,
        availability_date=availability.availability_date,
        free=3,
        total=10,
        occupancy_percent=70.0,
        occupancy_status="high",
        reservation_status="unknown",
        hut_type=hut.hut_type_open,
        first_checked=day_start,
        last_checked=day_start,
    )
    return hut, availability.availability_date


@pytest.mark.django_db
class TestAvailabilityQueryCount:
    """Availability endpoints (OpenSpec phase 3.3).

    ``get_hut_availability_current`` used to lazy-load
    ``hut_type_open``/``hut_type_closed`` after the fetch; both now ride
    along in the main query. geojson is one SQL aggregate; trend was
    already minimal.
    """

    def test_current_pinned(self, availability_hut):
        hut, date = availability_hut
        client = Client()
        with CaptureQueriesContext(connection) as ctx:
            response = client.get(
                f"/v1/huts/{hut.slug}/availability/{date.isoformat()}"
            )
        assert response.status_code == 200
        assert len(ctx) == AVAILABILITY_CURRENT_PIN, (
            f"get_hut_availability_current issued {len(ctx)} queries "
            f"(pin: {AVAILABILITY_CURRENT_PIN}) — hut type joins must ride "
            "along with the hut fetch; no lazy loads."
        )

    def test_trend_pinned(self, availability_hut):
        hut, date = availability_hut
        client = Client()
        with CaptureQueriesContext(connection) as ctx:
            response = client.get(
                f"/v1/huts/{hut.slug}/availability/{date.isoformat()}/trend"
            )
        assert response.status_code == 200
        assert len(ctx) == AVAILABILITY_TREND_PIN, (
            f"get_hut_availability_trend issued {len(ctx)} queries "
            f"(pin: {AVAILABILITY_TREND_PIN})."
        )

    def test_geojson_pinned(self, availability_hut):
        _hut, date = availability_hut
        client = Client()
        with CaptureQueriesContext(connection) as ctx:
            response = client.get(f"/v1/huts/availability/{date.isoformat()}.geojson")
        assert response.status_code == 200
        assert len(ctx) == AVAILABILITY_GEOJSON_PIN, (
            f"get_hut_availability_geojson issued {len(ctx)} queries "
            f"(pin: {AVAILABILITY_GEOJSON_PIN}) — the whole FeatureCollection "
            "is one SQL aggregate."
        )

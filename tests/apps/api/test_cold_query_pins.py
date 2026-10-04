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

SYMBOLS_LIST_PIN = 1
CATEGORIES_COLD_PIN = 1


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

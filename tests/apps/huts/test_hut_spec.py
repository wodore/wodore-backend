"""Query-count pins for the hut detail endpoint (OpenSpec phase 2.2).

These replace nplusone (removed with Django 6.1): the endpoint's query
count is part of its contract — a regression here fails the suite.
"""

import pytest

from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext

from server.apps.huts.models import Hut

# Recorded when the readers pilot landed (prepare_hut_detail: four joins
# + four aggregates in one query), against the seed_data fixture. The
# request total covers visit recording, ETag machinery, and the
# modified-timestamp lookup. Lane-DB runs may differ slightly (richer
# fixtures); the pin is the test-suite contract.
DETAIL_QUERY_PIN = 15


@pytest.mark.django_db
class TestHutDetailQueryCount:
    def test_detail_query_count_pinned(self, seed_data):
        slug = (
            Hut.objects.filter(is_active=True, is_public=True)
            .values_list("slug", flat=True)
            .first()
        )
        assert slug, "seed data has no public huts"
        client = Client()
        url = f"/v1/huts/{slug}?lang=de"

        # Warm once (schema/caches), then pin.
        assert client.get(url).status_code == 200
        with CaptureQueriesContext(connection) as ctx:
            response = client.get(url)
        assert response.status_code == 200
        assert len(ctx) == DETAIL_QUERY_PIN, (
            f"get_hut now issues {len(ctx)} queries (pin: {DETAIL_QUERY_PIN}). "
            "If this is an intentional change, update the pin with review."
        )

    def test_detail_main_query_is_single_pass(self, seed_data, db):
        """The readers-prepared core runs as ONE query (joins, no prefetch)."""
        from server.apps.huts.api._hut_spec import prepare_hut_detail

        slug = (
            Hut.objects.filter(is_active=True, is_public=True)
            .values_list("slug", flat=True)
            .first()
        )
        qs = prepare_hut_detail(
            Hut.objects.filter(is_active=True, is_public=True, slug=slug),
            media_url="/media/",
        )
        with CaptureQueriesContext(connection) as ctx:
            list(qs)
        assert len(ctx) == 1, (
            f"prepare_hut_detail must stay a single query (got {len(ctx)}) — "
            "prefetch-based relations would regress the detail endpoint."
        )

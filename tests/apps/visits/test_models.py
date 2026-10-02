"""Tests for the visit counter (spec: place-visit-counter).

Covers: visitor dedup within the window, no DB writes in the request path,
buffer-then-flush upserts per (content_type, object_id, day) for both
content types, operator/UA guard, enqueue-only behavior, popular_places.
"""

from unittest.mock import MagicMock

import pytest

from tests.apps.geometries.test_image_pinning import _result
from tests.helpers import PrefixedClient as TestClient

from django.core.cache import cache
from django.test import RequestFactory
from django.utils import timezone as djtz

from server.apps.geometries import image_response_cache as irc
from server.apps.geometries.pinning import pin_place_images, popular_places
from server.apps.visits import models as vc
from server.apps.visits.models import (
    ObjectVisitDay,
    flush_visit_counters,
    record_visit,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _isolated_response_cache(monkeypatch):
    from uuid import uuid4

    from django.core.cache.backends.locmem import LocMemCache

    monkeypatch.setattr(irc, "_cache", lambda: LocMemCache(f"test-{uuid4().hex}", {}))


@pytest.fixture(autouse=True)
def _isolated_default_cache():
    cache.clear()  # locmem per-test isolation


@pytest.fixture
def hut(seed_data):
    from server.apps.huts.models import Hut, HutImageAssociation

    hut = Hut.objects.filter(is_active=True, is_public=True).first()
    assert hut is not None
    HutImageAssociation.objects.filter(hut=hut).delete()
    return hut


def _request(ua="Mozilla/5.0 TestBrowser", ip="203.0.113.1", **params):
    rf = RequestFactory()
    return rf.get(
        "/v1/geo/images/hut/x",
        params or {"radius": "50"},
        REMOTE_ADDR=ip,
        HTTP_USER_AGENT=ua,
        HTTP_X_FORWARDED_FOR=ip,
    )


def _buffer_key(obj) -> str:
    """Reconstruct the buffer key record_visit used for obj today."""
    from django.contrib.contenttypes.models import ContentType
    from django.utils import timezone

    ct = ContentType.objects.get_for_model(obj)
    day = timezone.now().date().isoformat()
    return f"visitcount:buffer:{ct.pk}:{obj.pk}:{day}"


def _flush(objs) -> int:
    """Flush the buffer keys for objs (as the q2 task would)."""
    flushed = 0
    for obj in objs:
        key = _buffer_key(obj)
        if key in cache:
            flush_visit_counters(key)
            flushed += 1
    return flushed


class TestRecordVisit:
    def test_first_hit_buffers(self, hut):
        enqueued = []
        import django_q.tasks as qtasks

        original = qtasks.async_task

        def _fake_async_task(func, *args, **kwargs):
            enqueued.append(func)

        qtasks.async_task = _fake_async_task
        try:
            assert record_visit(_request(), hut) is True
        finally:
            qtasks.async_task = original
        assert enqueued == ["server.apps.visits.models.flush_visit_counters"]
        assert ObjectVisitDay.objects.count() == 0  # no DB write in-request

    def test_repeat_within_window_counts_once(self, hut):
        request = _request()
        assert record_visit(request, hut) is True
        assert record_visit(_request(), hut) is False  # same visitor+ip
        assert record_visit(_request(ip="198.51.100.9"), hut) is True  # other visitor

    def test_different_visitor_dedup_is_per_object(self, hut, seed_data):
        from server.apps.geometries.models import GeoPlace

        place = GeoPlace.objects.filter(is_active=True, is_public=True).first()
        request = _request()
        assert record_visit(request, hut) is True
        assert record_visit(_request(), place) is True  # same visitor, new object

    def test_operator_and_prefetch_skipped(self, hut):
        assert record_visit(_request(update_cache="true"), hut) is False
        assert record_visit(_request(ua="python-requests/2.31"), hut) is False
        assert record_visit(_request(ua="curl/8.1"), hut) is False

    def test_never_raises(self, hut, monkeypatch):
        monkeypatch.setattr(vc, "_cache", MagicMock(side_effect=RuntimeError("boom")))
        assert record_visit(_request(), hut) is False  # swallowed


class TestFlush:
    def test_flush_upserts_one_row_per_object_day(self, hut, seed_data):
        from server.apps.geometries.models import GeoPlace

        place = GeoPlace.objects.filter(is_active=True, is_public=True).first()
        record_visit(_request(ip="1.1.1.1"), hut)
        record_visit(_request(ip="2.2.2.2"), hut)
        record_visit(_request(ip="3.3.3.3"), place)

        assert _flush([hut, place]) == 2

        rows = ObjectVisitDay.objects.all()
        assert rows.count() == 2  # one per (object, day)
        hut_row = rows.get(object_id=hut.pk, content_type__model="hut")
        assert hut_row.count == 2
        place_row = rows.get(object_id=place.pk, content_type__model="geoplace")
        assert place_row.count == 1

    def test_flush_accumulates_across_flushes(self, hut):
        record_visit(_request(ip="1.1.1.1"), hut)
        _flush([hut])
        record_visit(_request(ip="2.2.2.2"), hut)
        _flush([hut])
        row = ObjectVisitDay.objects.get(object_id=hut.pk)
        assert row.count == 2

    def test_timestamps_present(self, hut):
        record_visit(_request(), hut)
        _flush([hut])
        row = ObjectVisitDay.objects.get(object_id=hut.pk)
        assert row.created is not None and row.modified is not None


class TestPopularPlaces:
    def test_sums_window_and_orders(self, seed_data):
        from django.contrib.contenttypes.models import ContentType

        from server.apps.geometries.models import GeoPlace

        ct = ContentType.objects.get_for_model(GeoPlace)
        places = list(GeoPlace.objects.filter(is_active=True, is_public=True)[:3])
        ObjectVisitDay.objects.create(
            content_type=ct, object_id=places[0].pk, day=djtz.now().date(), count=10
        )
        ObjectVisitDay.objects.create(
            content_type=ct, object_id=places[1].pk, day=djtz.now().date(), count=30
        )
        result = list(popular_places(limit=2))
        assert result[0]["object_id"] == places[1].pk
        assert result[0]["total"] == 30
        assert result[1]["object_id"] == places[0].pk


class TestEndpointCounting:
    """Visit counting on the hut detail endpoint, not the images endpoint."""

    def test_hut_detail_counts_visit(self, hut, client, monkeypatch):
        calls = []
        monkeypatch.setattr(
            "django_q.tasks.async_task",
            lambda func, *a, **kw: calls.append(func),
        )
        response = client.get(f"/v1/huts/{hut.slug}")
        assert response.status_code == 200
        assert calls  # flush task enqueued via the buffer
        assert ObjectVisitDay.objects.count() == 0  # still no in-request write

    def test_images_endpoint_does_not_count(self, hut, monkeypatch):
        calls = []
        monkeypatch.setattr(
            "django_q.tasks.async_task",
            lambda func, *a, **kw: calls.append(func),
        )
        pin_place_images(hut, [_result(score=80)])
        client = TestClient("/v1/geo/images")
        response = client.get(f"/hut/{hut.slug}?radius=50&lang=en&limit=10")
        assert response.status_code == 200
        assert not [c for c in calls if "visit" in str(c)]  # no visit flush

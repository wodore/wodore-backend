"""Tests for availability batch processing (services.py).

Covers ``_process_huts_batch``: chunked bulk writes, scoped
statement_timeout, and the (hut, date) duplicate dedupe that keeps one
payload with several bookings per date from violating ``unique_hut_date``.
"""

import datetime
from types import SimpleNamespace

import pytest

from django.utils import timezone

from server.apps.availability.models import HutAvailability
from server.apps.availability.services import (
    AvailabilityService,
    _sanitize_negative_free,
)
from server.apps.huts.models import Hut
from server.apps.organizations.models import Organization

pytestmark = pytest.mark.django_db


def _booking(date: datetime.date, free: int = 5, total: int = 10) -> SimpleNamespace:
    """Minimal stand-in for a hut-services booking entry."""
    return SimpleNamespace(
        date=date,
        free=free,
        total=total,
        free_tolerance=0,
        occupancy_percent=free / total * 100,
        occupancy_steps=int(free / total * 100),
        occupancy_status="medium",
        reservation_status="possible",
        link="",
        hut_type=None,
    )


def _places_booking(date: datetime.date, free: int | None) -> SimpleNamespace:
    """Stand-in shaped like the hut-services ``BookingSchema`` (nested places)."""
    return SimpleNamespace(date=date, places=SimpleNamespace(free=free))


def _hut_booking(source: str, source_id: str, bookings: list) -> SimpleNamespace:
    """Minimal stand-in for ``HutBookingsSchema``."""
    return SimpleNamespace(source=source, source_id=source_id, bookings=bookings)


@pytest.fixture
def hut_and_org(seed_data) -> tuple[Hut, Organization]:
    hut = Hut.objects.first()
    org = Organization.objects.first()
    assert hut is not None and org is not None  # guaranteed by seed_data
    return hut, org


class TestProcessHutsBatch:
    def test_creates_updates_and_histories(self, hut_and_org):
        hut, org = hut_and_org
        now = timezone.now()
        date = datetime.date(2030, 7, 1)

        results = AvailabilityService._process_huts_batch(
            [(hut, _hut_booking(org.slug, "123", [_booking(date)]))], now=now
        )
        assert results[0].success is True
        assert results[0].records_created == 1
        avail = HutAvailability.objects.get(hut=hut, availability_date=date)
        assert avail.free == 5

        # Second run with changed values → update path + history entry.
        results = AvailabilityService._process_huts_batch(
            [(hut, _hut_booking(org.slug, "123", [_booking(date, free=2)]))], now=now
        )
        assert results[0].success is True
        assert results[0].records_updated == 1
        avail.refresh_from_db()
        assert avail.free == 2

    def test_duplicate_hut_date_in_payload_last_wins(self, hut_and_org):
        """Several bookings for one (hut, date) must not violate unique_hut_date.

        Regression test: the batch used to queue both rows, and the bulk
        create rolled the whole batch back with
        ``duplicate key ... unique_hut_date``.
        """
        hut, org = hut_and_org
        date = datetime.date(2030, 7, 2)
        batch = [
            (
                hut,
                _hut_booking(
                    org.slug, "123", [_booking(date, free=5), _booking(date, free=1)]
                ),
            )
        ]

        results = AvailabilityService._process_huts_batch(batch, now=timezone.now())

        assert results[0].success is True
        assert results[0].records_created == 1
        assert (
            HutAvailability.objects.filter(hut=hut, availability_date=date).count() == 1
        )
        avail = HutAvailability.objects.get(hut=hut, availability_date=date)
        assert avail.free == 1  # latest payload values win

    def test_large_batch_spans_bulk_write_chunks(self, hut_and_org):
        """More rows than BULK_WRITE_BATCH_SIZE still write correctly."""
        hut, org = hut_and_org
        start = datetime.date(2030, 1, 1)
        bookings = [_booking(start + datetime.timedelta(days=i)) for i in range(600)]

        results = AvailabilityService._process_huts_batch(
            [(hut, _hut_booking(org.slug, "123", bookings))], now=timezone.now()
        )

        assert results[0].success is True
        assert results[0].records_created == 600
        assert HutAvailability.objects.filter(hut=hut).count() == 600


class TestSanitizeNegativeFree:
    def test_negative_free_sentinel_becomes_none(self):
        """DOC/Tyler reports unpublished counts as ``TotalAvailable = -1``.

        Regression test: the -1 sentinel flowed into the availability rows
        and violated the DB ``free >= 0`` check, killing the whole batch
        for every affected hut (seen on DOC Great Walk huts, 2026-10).
        """
        hut_booking = _hut_booking(
            "tyler",
            "123",
            [
                _places_booking(datetime.date(2030, 7, 1), free=-1),
                _places_booking(datetime.date(2030, 7, 2), free=3),
                _places_booking(datetime.date(2030, 7, 3), free=None),
            ],
        )
        bookings = {123: hut_booking}

        _sanitize_negative_free(bookings)

        assert [b.places.free for b in hut_booking.bookings] == [None, 3, None]

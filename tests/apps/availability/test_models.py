"""Tests for availability models: HutAvailability free_tolerance handling."""

import datetime

import pytest

from django.utils import timezone

from server.apps.availability.models import HutAvailability
from server.apps.huts.models import Hut
from server.apps.organizations.models import Organization

pytestmark = pytest.mark.django_db


def _make_availability(hut: Hut, org: Organization) -> HutAvailability:
    now = timezone.now()
    return HutAvailability.objects.create(
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


class TestFreeTolerance:
    def test_default_zero(self, seed_data) -> None:
        avail = _make_availability(Hut.objects.first(), Organization.objects.first())
        assert avail.free_tolerance == 0

    def test_update_availability_records_tolerance(self, seed_data) -> None:
        avail = _make_availability(Hut.objects.first(), Organization.objects.first())
        changed, history = avail.update_availability(
            free=10,  # same free
            total=50,  # same total
            occupancy_percent=avail.occupancy_percent,
            occupancy_steps=avail.occupancy_steps,
            occupancy_status=avail.occupancy_status,
            reservation_status=avail.reservation_status,
            free_tolerance=5,  # NEW tolerance -> change detected
        )
        assert changed is True
        assert history is not None
        avail.refresh_from_db()
        assert avail.free_tolerance == 5
        assert history.free_tolerance == 5

    def test_tolerance_change_alone_flags_change(self, seed_data) -> None:
        avail = _make_availability(Hut.objects.first(), Organization.objects.first())
        assert (
            avail.has_changed(
                free=10,
                total=50,
                reservation_status=avail.reservation_status,
                free_tolerance=4,
            )
            is True
        )
        assert (
            avail.has_changed(
                free=10,
                total=50,
                reservation_status=avail.reservation_status,
                free_tolerance=0,
            )
            is False
        )

    def test_history_records_tolerance_snapshot(self, seed_data) -> None:
        avail = _make_availability(Hut.objects.first(), Organization.objects.first())
        history = avail.record_change(
            free=8,
            total=50,
            occupancy_percent=84.0,
            occupancy_status="high",
            reservation_status="possible",
            free_tolerance=7,
        )
        assert history.free == 8
        assert history.free_tolerance == 7

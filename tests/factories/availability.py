import datetime

import factory

from django.utils import timezone

from server.apps.availability.models import HutAvailability

from . import OrganizationFactory
from .huts import HutFactory


def _get_occupancy(free: int, total: int) -> tuple[float, int, str]:
    """Calculate occupancy percent, steps, and status from free/total values."""
    if total == 0:
        return 0.0, 0, "unknown"
    occupied = total - free
    percent = round((occupied / total) * 100, 1)
    steps = round(percent / 10) * 10
    if percent == 0:
        status = "empty"
    elif percent <= 25:
        status = "low"
    elif percent <= 60:
        status = "medium"
    elif percent < 100:
        status = "high"
    else:
        status = "full"
    return percent, steps, status


from typing import Any


def _occ_percent(obj: Any) -> Any:
    return _get_occupancy(obj.free, obj.total)[0]


def _occ_steps(obj: Any) -> Any:
    return _get_occupancy(obj.free, obj.total)[1]


def _occ_status(obj: Any) -> Any:
    return _get_occupancy(obj.free, obj.total)[2]


class AvailabilityFactory(factory.django.DjangoModelFactory[HutAvailability]):
    class Meta:
        model = HutAvailability

    hut = factory.SubFactory(HutFactory)
    source_organization = factory.SubFactory(OrganizationFactory)
    source_id = factory.Sequence(str)
    availability_date = factory.LazyFunction(datetime.date.today)
    free = 10
    total = 50
    occupancy_percent = factory.LazyAttribute(_occ_percent)
    occupancy_steps = factory.LazyAttribute(_occ_steps)
    occupancy_status = factory.LazyAttribute(_occ_status)
    reservation_status = "possible"
    first_checked = factory.LazyFunction(timezone.now)
    last_checked = factory.LazyFunction(timezone.now)

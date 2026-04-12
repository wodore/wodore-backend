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


class AvailabilityFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = HutAvailability

    hut = factory.SubFactory(HutFactory)
    source_organization = factory.SubFactory(OrganizationFactory)
    source_id = factory.Sequence(lambda n: str(n))
    availability_date = factory.LazyFunction(datetime.date.today)
    free = 10
    total = 50
    occupancy_percent = factory.LazyAttribute(
        lambda o: _get_occupancy(o.free, o.total)[0]
    )
    occupancy_steps = factory.LazyAttribute(
        lambda o: _get_occupancy(o.free, o.total)[1]
    )
    occupancy_status = factory.LazyAttribute(
        lambda o: _get_occupancy(o.free, o.total)[2]
    )
    reservation_status = "possible"
    first_checked = factory.LazyFunction(timezone.now)
    last_checked = factory.LazyFunction(timezone.now)

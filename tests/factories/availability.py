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


def _mirror_to_place(row: HutAvailability) -> None:
    """Phase D (geoplace-availability): readers serve from the place
    tables — mirror every factory row so tests exercise the real read
    path. Creates a linked place for factory-fresh huts when needed."""
    from server.apps.availability.models import GeoPlaceAvailability
    from server.apps.availability.place_link import resolve_place
    from server.apps.geometries.models import GeoPlace, GeoPlaceSourceAssociation
    from server.apps.organizations.models import Organization

    place = resolve_place(row.hut)
    if place is None:
        place = GeoPlace.objects.create(
            slug=f"pl-{row.hut.slug}"[:15],
            name=f"Place {row.hut.name}",
            location=row.hut.location,
            country_code=row.hut.country_field or "CH",
        )
        wodore, _ = Organization.objects.get_or_create(slug="wodore")
        GeoPlaceSourceAssociation.objects.create(
            organization=wodore, geo_place=place, source_id=row.hut.slug
        )
    GeoPlaceAvailability.objects.create(
        geo_place=place,
        source_organization=row.source_organization,
        source_id=row.source_id,
        availability_date=row.availability_date,
        free=row.free,
        total=row.total,
        free_tolerance=row.free_tolerance or 0,
        occupancy_percent=row.occupancy_percent,
        occupancy_steps=row.occupancy_steps,
        occupancy_status=row.occupancy_status,
        reservation_status=row.reservation_status,
        link=row.link,
        hut_type=row.hut_type,
        first_checked=row.first_checked,
        last_checked=row.last_checked,
    )


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

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        row = super()._create(model_class, *args, **kwargs)
        _mirror_to_place(row)
        return row

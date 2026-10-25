from collections.abc import Callable

import factory


def _fmt_seq(prefix: str) -> Callable[[int], str]:
    """Typed factory.Sequence helper (factory_boy's Sequence param is untyped)."""

    def _seq(n: int) -> str:
        return f"{prefix}{n}"

    return _seq


from django.contrib.gis.geos import Point

from server.apps.categories.models import Category
from server.apps.organizations.models import Organization


def random_swiss_point() -> Point:
    """Generate a random Point within Switzerland (SRID 4326)."""
    import random

    lon = round(random.uniform(5.9, 10.5), 6)
    lat = round(random.uniform(45.8, 47.8), 6)
    return Point(x=lon, y=lat, srid=4326)


class CategoryFactory(factory.django.DjangoModelFactory[Category]):
    class Meta:
        model = Category

    slug = factory.Sequence(_fmt_seq("cat-"))
    name = factory.Sequence(_fmt_seq("Category "))


class OrganizationFactory(factory.django.DjangoModelFactory[Organization]):
    class Meta:
        model = Organization
        django_get_or_create = ("slug",)

    slug = factory.Sequence(_fmt_seq("org-"))
    name = factory.Sequence(_fmt_seq("Organization "))


# Re-export all factories from app modules for convenience
# Usage: from tests.factories import HutFactory
#    or: from tests.factories.huts import HutFactory
from .availability import AvailabilityFactory
from .contacts import ContactFactory, ContactFunctionFactory
from .geometries import GeoPlaceFactory
from .huts import HutFactory
from .owners import OwnerFactory

__all__ = [
    "AvailabilityFactory",
    "CategoryFactory",
    "ContactFactory",
    "ContactFunctionFactory",
    "GeoPlaceFactory",
    "HutFactory",
    "OrganizationFactory",
    "OwnerFactory",
    "random_swiss_point",
]

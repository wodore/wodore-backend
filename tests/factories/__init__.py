import factory
from django.contrib.gis.geos import Point

from server.apps.categories.models import Category
from server.apps.organizations.models import Organization


def random_swiss_point() -> Point:
    """Generate a random Point within Switzerland (SRID 4326)."""
    import random

    lon = round(random.uniform(5.9, 10.5), 6)
    lat = round(random.uniform(45.8, 47.8), 6)
    return Point(x=lon, y=lat, srid=4326)


class CategoryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Category

    slug = factory.Sequence(lambda n: f"cat-{n}")
    name = factory.Sequence(lambda n: f"Category {n}")


class OrganizationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Organization
        django_get_or_create = ("slug",)

    slug = factory.Sequence(lambda n: f"org-{n}")
    name = factory.Sequence(lambda n: f"Organization {n}")


# Re-export all factories from app modules for convenience
# Usage: from tests.factories import HutFactory
#    or: from tests.factories.huts import HutFactory
from .availability import AvailabilityFactory  # noqa: E402
from .contacts import ContactFactory, ContactFunctionFactory  # noqa: E402
from .geometries import GeoPlaceFactory  # noqa: E402
from .huts import HutFactory  # noqa: E402
from .owners import OwnerFactory  # noqa: E402

__all__ = [
    "random_swiss_point",
    "CategoryFactory",
    "OrganizationFactory",
    "HutFactory",
    "ContactFactory",
    "ContactFunctionFactory",
    "GeoPlaceFactory",
    "AvailabilityFactory",
    "OwnerFactory",
]

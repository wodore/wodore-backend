from typing import Any

import factory

from server.apps.huts.models import Hut, HutOrganizationAssociation
from server.apps.organizations.models import Organization

from . import _fmt_seq, random_swiss_point


class HutFactory(factory.django.DjangoModelFactory[Hut]):
    class Meta:
        model = Hut
        skip_postgeneration_save = True

    name = factory.Sequence(_fmt_seq("Test Hut "))
    location = factory.LazyFunction(random_swiss_point)
    country_field = "CH"
    is_active = True
    is_public = True
    elevation = factory.LazyFunction(lambda: __import__("random").randint(1000, 3500))
    capacity_open = factory.LazyFunction(lambda: __import__("random").randint(10, 120))

    # Accommodation child (kind-guard requires mode classifiers only under
    # accommodation; a root-level factory category would be rejected).
    @factory.lazy_attribute
    def hut_type_open(self):  # type: ignore[no-untyped-def]
        from server.apps.categories.models import Category

        parent = Category.objects.get(slug="accommodation", parent__slug="amenity")
        category, _created = Category.objects.get_or_create(
            slug="factory-hut", parent=parent, defaults={"name": "Factory Hütte"}
        )
        return category

    @factory.post_generation
    def organizations(self, create: bool, extracted: list[Any] | None, **kwargs: Any):
        if not create:
            return
        if extracted:
            for org_data in extracted:
                if isinstance(org_data, dict):
                    HutOrganizationAssociation.objects.create(
                        hut=self,
                        organization=org_data["organization"],
                        source_id=org_data.get("source_id", ""),
                    )
                elif isinstance(org_data, Organization):
                    HutOrganizationAssociation.objects.create(
                        hut=self,
                        organization=org_data,
                    )

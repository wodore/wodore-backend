import factory

from server.apps.huts.models import Hut, HutOrganizationAssociation
from server.apps.organizations.models import Organization

from . import CategoryFactory, random_swiss_point


class HutFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Hut
        skip_postgeneration_save = True

    name = factory.Sequence(lambda n: f"Test Hut {n}")
    location = factory.LazyFunction(random_swiss_point)
    country_field = "CH"
    is_active = True
    is_public = True
    elevation = factory.LazyFunction(lambda: __import__("random").randint(1000, 3500))
    capacity_open = factory.LazyFunction(lambda: __import__("random").randint(10, 120))
    hut_type_open = factory.SubFactory(CategoryFactory)

    @factory.post_generation
    def organizations(self, create, extracted, **kwargs):
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

import factory

from server.apps.geometries.models import GeoPlace

from . import random_swiss_point


class GeoPlaceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = GeoPlace
        skip_postgeneration_save = True

    name = factory.Sequence(lambda n: f"Test Place {n}")
    location = factory.LazyFunction(random_swiss_point)
    country_code = "CH"
    is_active = True
    importance = factory.LazyFunction(lambda: __import__("random").randint(10, 90))

    @factory.post_generation
    def category_list(self, create, extracted, **kwargs):
        if not create:
            return
        if extracted:
            for cat in extracted:
                self.categories.add(cat)

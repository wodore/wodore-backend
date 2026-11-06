from typing import Any

import factory

from server.apps.geometries.models import GeoPlace

from . import _fmt_seq, random_swiss_point


class GeoPlaceFactory(factory.django.DjangoModelFactory[GeoPlace]):
    class Meta:
        model = GeoPlace
        skip_postgeneration_save = True

    name = factory.Sequence(_fmt_seq("Test Place "))
    location = factory.LazyFunction(random_swiss_point)
    country_code = "CH"
    is_active = True
    importance = factory.LazyFunction(lambda: __import__("random").randint(10, 90))

    @factory.post_generation
    def category_list(self, create: bool, extracted: list[Any] | None, **kwargs: Any):
        if not create:
            return
        if extracted:
            for cat in extracted:
                self.categories.add(cat)  # type: ignore  # dynamic attr: plugin-less inference gap

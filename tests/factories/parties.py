import factory

from server.apps.parties.models import Party


class PartyFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Party
        skip_postgeneration_save = True

    slug = factory.Sequence(lambda n: f"party-{n}")
    name = factory.Sequence(lambda n: f"Test Party {n}")

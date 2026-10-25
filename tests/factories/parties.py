import factory

from server.apps.parties.models import Party

from . import _fmt_seq


class PartyFactory(factory.django.DjangoModelFactory[Party]):
    class Meta:
        model = Party
        skip_postgeneration_save = True

    slug = factory.Sequence(_fmt_seq("party-"))
    name = factory.Sequence(_fmt_seq("Test Party "))

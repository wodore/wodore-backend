import factory

from server.apps.owners.models import Owner

from . import _fmt_seq


class OwnerFactory(factory.django.DjangoModelFactory[Owner]):
    class Meta:
        model = Owner

    slug = factory.Sequence(_fmt_seq("owner-"))
    name = factory.Sequence(_fmt_seq("Owner "))

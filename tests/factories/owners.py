import factory

from server.apps.owners.models import Owner


class OwnerFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Owner

    slug = factory.Sequence(lambda n: f"owner-{n}")
    name = factory.Sequence(lambda n: f"Owner {n}")

import factory

from server.apps.contacts.models import Contact, ContactFunction


class ContactFunctionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ContactFunction

    slug = factory.Sequence(lambda n: f"function-{n}")
    name = factory.Sequence(lambda n: f"Function {n}")
    priority = 10


class ContactFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Contact

    name = factory.Faker("name")
    email = factory.Faker("email")
    phone = factory.LazyFunction(
        lambda: f"+41 {__import__('random').randint(100, 999)} "
        f"{__import__('random').randint(100, 999)} {__import__('random').randint(100, 999)}"
    )
    function = factory.SubFactory(ContactFunctionFactory)
    is_active = True

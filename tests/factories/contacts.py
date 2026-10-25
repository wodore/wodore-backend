import factory

from server.apps.contacts.models import Contact, ContactFunction

from . import _fmt_seq


class ContactFunctionFactory(factory.django.DjangoModelFactory[ContactFunction]):
    class Meta:
        model = ContactFunction

    slug = factory.Sequence(_fmt_seq("function-"))
    name = factory.Sequence(_fmt_seq("Function "))
    priority = 10


class ContactFactory(factory.django.DjangoModelFactory[Contact]):
    class Meta:
        model = Contact

    name = factory.Faker("name")
    email = factory.Faker("email")
    phone = factory.LazyFunction(
        lambda: (
            f"+41 {__import__('random').randint(100, 999)} "
            f"{__import__('random').randint(100, 999)} {__import__('random').randint(100, 999)}"
        )
    )
    function = factory.SubFactory(ContactFunctionFactory)
    is_active = True

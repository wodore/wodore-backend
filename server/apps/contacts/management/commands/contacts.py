import random

from faker import Faker

from server.core.management import CRUDCommand

from ...models import Contact, ContactFunction


def add_contact_function(parser, limit, **kwargs):
    fake = Faker(["de", "fr", "it"])
    contact_functions_pks = ContactFunction.objects.all().values_list("pk", flat=True)
    parser.stdout.write("Add contacts:")
    for _ in range(limit):
        contact = Contact(
            name=fake.name(),
            email="" if random.randint(0, 10) < 2 else fake.email(),
            phone="" if random.randint(0, 3) else fake.phone_number(),
            mobile="" if random.randint(0, 3) else fake.phone_number(),
            address="" if random.randint(0, 5) else fake.address(),
            note="" if random.randint(0, 5) else fake.paragraph(2),
            url="" if random.randint(0, 10) else fake.uri(),
            is_active=random.randint(0, 10) > 3,
            is_public=random.randint(0, 10) > 3,
            function_id=random.choice(contact_functions_pks),
        )
        contact.save()
        parser.stdout.write(f"  - {contact}")
    parser.stdout.write(
        parser.style.SUCCESS(f"Successfully added {limit} new contacts")
    )


class Command(CRUDCommand):
    help = "Add random contacts."
    use_limit_arg = True
    model = Contact
    model_names = "contacts"
    add_function = add_contact_function

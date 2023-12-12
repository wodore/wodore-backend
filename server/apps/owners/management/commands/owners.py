import random

from faker import Faker

from django.db import IntegrityError
from django.utils.text import slugify

from server.core.management import CRUDCommand

from ...models import Owner  # , Contact


def add_owner_function(parser, limit, **kwargs):
    fake = Faker(["de", "fr", "it"])
    # contact_functions_pks = ContactFunction.objects.all().values_list("pk", flat=True)
    parser.stdout.write("Add owners:")
    added = 0
    for _ in range(limit):
        name = fake.company()
        slug = slugify(name)
        owner = Owner(
            slug=slug,
            name_de=name,
            note="" if random.randint(0, 3) else fake.paragraph(4),
            url="" if random.randint(0, 10) < 3 else fake.uri(),
        )
        try:
            owner.save()
            added += 1
        except IntegrityError as e:
            parser.stdout.write(parser.style.WARNING(f"Could not add '{owner}' to the database due to:"))
            parser.stdout.write(parser.style.NOTICE(e.args[0].strip()))
        parser.stdout.write(f"  - {owner}")
    parser.stdout.write(parser.style.SUCCESS(f"Successfully added {added} new owners"))


class Command(CRUDCommand):
    help = "Add random owners."
    use_limit_arg = True
    model = Owner
    model_names = "owners"
    add_function = add_owner_function

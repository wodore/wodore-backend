# Generated manually — renames existing contact-function symbols onto
# their content-hashed canonical names (see server.core.storage).
# Reverse is a documented no-op.

from django.db import migrations

from server.core.storage import canonicalize_field_storage


def canonicalize(apps, schema_editor):
    ContactFunction = apps.get_model("contacts", "ContactFunction")
    canonicalize_field_storage(ContactFunction, "symbol")


class Migration(migrations.Migration):
    dependencies = [
        ("contacts", "0004_alter_contactfunction_symbol"),
    ]

    operations = [
        migrations.RunPython(canonicalize, migrations.RunPython.noop),
    ]

# Generated manually — renames existing organization logos onto their
# content-hashed canonical names (see server.core.storage). Logos are
# admin-uploaded under original filenames; media is immutable-cached, so
# a URL must never change content. Reverse is a documented no-op.

from django.db import migrations

from server.core.storage import canonicalize_field_storage


def canonicalize(apps, schema_editor):
    Organization = apps.get_model("organizations", "Organization")
    canonicalize_field_storage(Organization, "logo")


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0021_alter_organization_logo"),
    ]

    operations = [
        migrations.RunPython(canonicalize, migrations.RunPython.noop),
    ]

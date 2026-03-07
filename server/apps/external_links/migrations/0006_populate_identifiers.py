from django.db import migrations
import secrets
import string


def generate_identifier():
    """Generate a 6-character identifier."""
    charset = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(charset) for _ in range(6))


def populate_identifiers(apps, schema_editor):
    """Populate identifiers for existing ExternalLink records."""
    ExternalLink = apps.get_model("external_links", "ExternalLink")

    for link in ExternalLink.objects.filter(identifier__isnull=True):
        # Generate unique identifier with retry logic
        for attempt in range(10):
            identifier = generate_identifier()
            if not ExternalLink.objects.filter(identifier=identifier).exclude(id=link.id).exists():
                link.identifier = identifier
                link.save(update_fields=["identifier"])
                break


def reverse_populate_identifiers(apps, schema_editor):
    """Reverse: Set all identifiers to None."""
    ExternalLink = apps.get_model("external_links", "ExternalLink")
    ExternalLink.objects.update(identifier=None)


class Migration(migrations.Migration):

    dependencies = [
        ("external_links", "0005_remove_externallink_slug_externallink_identifier"),
    ]

    operations = [
        migrations.RunPython(populate_identifiers, reverse_populate_identifiers),
    ]

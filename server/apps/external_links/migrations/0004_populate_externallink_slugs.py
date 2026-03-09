from django.db import migrations
import secrets
import string
from slugify import slugify as pyslugify


def generate_slug(label):
    """Generate a simple slug from label."""
    base_slug = pyslugify(label, word_boundary=True)
    base_slug = base_slug[:40].rstrip("-")
    if len(base_slug) < 3:
        base_slug = "link"

    charset = string.ascii_lowercase + string.digits
    suffix = "".join(secrets.choice(charset) for _ in range(4))
    return f"{base_slug}-{suffix}"


def populate_slugs(apps, schema_editor):
    """Populate slugs for existing ExternalLink records."""
    ExternalLink = apps.get_model("external_links", "ExternalLink")

    for link in ExternalLink.objects.filter(slug__isnull=True):
        if link.label:
            # Generate unique slug with retry logic
            for attempt in range(10):
                slug = generate_slug(link.label)
                if not ExternalLink.objects.filter(slug=slug).exclude(id=link.id).exists():
                    link.slug = slug
                    link.save(update_fields=["slug"])
                    break


def reverse_populate_slugs(apps, schema_editor):
    """Reverse: Set all slugs to None."""
    ExternalLink = apps.get_model("external_links", "ExternalLink")
    ExternalLink.objects.update(slug=None)


class Migration(migrations.Migration):

    dependencies = [
        ("external_links", "0003_externallink_slug_alter_externallink_is_public"),
    ]

    operations = [
        migrations.RunPython(populate_slugs, reverse_populate_slugs),
    ]

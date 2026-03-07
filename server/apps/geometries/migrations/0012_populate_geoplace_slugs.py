# Generated manually for WEP008

from django.db import migrations, models
from django.utils.text import slugify


def populate_slugs(apps, schema_editor):
    """Populate slugs for existing GeoPlace records."""
    GeoPlace = apps.get_model("geometries", "GeoPlace")

    # Use .all() without ordering to avoid issues with default ordering
    for place in GeoPlace.objects.all().order_by('id').filter(slug__isnull=True).iterator():
        # Generate base slug from name
        base_slug = slugify(place.name)
        if not base_slug:
            base_slug = f"place-{place.id}"

        # Ensure uniqueness
        slug = base_slug
        counter = 1
        while GeoPlace.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1

        place.slug = slug
        place.save(update_fields=["slug"])


class Migration(migrations.Migration):

    dependencies = [
        ("geometries", "0011_update_source_id_field_and_indexes"),
    ]

    operations = [
        # Add slug field as nullable first
        migrations.AddField(
            model_name="geoplace",
            name="slug",
            field=models.SlugField(
                null=True,
                blank=True,
                max_length=200,
                verbose_name="Slug",
                help_text="Unique URL identifier",
            ),
        ),
        # Populate slugs
        migrations.RunPython(populate_slugs, migrations.RunPython.noop),
        # Now make the field unique and not nullable
        migrations.AlterField(
            model_name="geoplace",
            name="slug",
            field=models.SlugField(
                max_length=200,
                unique=True,
                verbose_name="Slug",
                help_text="Unique URL identifier",
            ),
        ),
    ]

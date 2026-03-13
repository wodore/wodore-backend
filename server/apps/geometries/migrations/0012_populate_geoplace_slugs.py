# Generated manually for WEP008 - Optimized slug generation

from django.db import migrations, models


def populate_slugs_fast(apps, schema_editor):
    """Populate slugs for existing GeoPlace records using bulk operations."""
    GeoPlace = apps.get_model("geometries", "GeoPlace")
    Category = apps.get_model("categories", "Category")
    GeoPlaceCategory = apps.get_model("geometries", "GeoPlaceCategory")
    db_alias = schema_editor.connection.alias

    # Build a mapping of place_id -> category_slug
    # Use the first category for each place as fallback
    category_map = {}
    if hasattr(GeoPlaceCategory, 'objects'):
        category_links = (
            GeoPlaceCategory.objects.using(db_alias)
            .select_related('category')
            .all()
            .iterator()
        )
        for link in category_links:
            if link.geo_place_id not in category_map:
                category_map[link.geo_place_id] = link.category.slug if link.category else None

    batch = []
    batch_size = 1000

    # Use iterator() to avoid loading all into memory
    places = (
        GeoPlace.objects.using(db_alias)
        .filter(slug__isnull=True)
        .order_by('id')
        .iterator(chunk_size=1000)
    )

    for place in places:
        # Get category slug for fallback
        category_slug = category_map.get(place.id)

        # Generate slug without DB check (UUID-based uniqueness)
        slug = GeoPlace.generate_unique_slug(
            name=place.name,
            category_slug=category_slug
        )

        place.slug = slug
        batch.append(place)

        if len(batch) >= batch_size:
            GeoPlace.objects.using(db_alias).bulk_update(
                batch,
                ['slug'],
                batch_size=1000
            )
            batch = []

    if batch:
        GeoPlace.objects.using(db_alias).bulk_update(batch, ['slug'], batch_size=1000)


class Migration(migrations.Migration):

    dependencies = [
        ("geometries", "0011_update_source_id_field_and_indexes"),
    ]

    operations = [
        # Add slug field as nullable first (fast operation)
        migrations.AddField(
            model_name="geoplace",
            name="slug",
            field=models.SlugField(
                null=True,
                blank=True,
                max_length=15,
                verbose_name="Slug",
                help_text="Unique URL identifier (max 15 chars)",
            ),
        ),
        # Populate slugs using optimized bulk operations (runs in seconds, not hours)
        migrations.RunPython(populate_slugs_fast, migrations.RunPython.noop),
        # Make the field not null and unique (fast because slug is already populated)
        migrations.AlterField(
            model_name="geoplace",
            name="slug",
            field=models.SlugField(
                max_length=15,
                unique=True,
                verbose_name="Slug",
                help_text="Unique URL identifier (max 15 chars)",
            ),
        ),
    ]

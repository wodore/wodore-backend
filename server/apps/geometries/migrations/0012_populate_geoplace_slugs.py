# Generated manually for WEP008 - Optimized slug generation
# This migration uses a simplified slug generator that doesn't depend on
# model relationships, which may not exist at this point in migration history.

from django.db import migrations, models
import secrets


def generate_slug_simple(name, category_slug=None, max_length=15):
    """
    Simple slug generator for migrations (no DB queries, no model dependencies).

    Format: {base_slug}-{uuid}
    - base_slug: 9 chars max
    - uuid: 5-6 chars
    - Total: max 15 chars
    """
    from slugify import slugify

    SLUG_IGNORE = [
        "hotel", "restaurant", "gasthaus", "gasthof", "berghaus",
        "berggasthaus", "hostel", "cafeteria", "campground",
    ]

    # Slugify the name
    if not name:
        base_slug = category_slug or "place"
    else:
        slug = slugify(name, separator="-")
        # Split into words and filter
        words = [w for w in slug.split("-") if w not in SLUG_IGNORE and len(w) >= 3]

        if not words:
            base_slug = category_slug or "place"
        else:
            # Take up to 3 words in original order
            selected_words = words[:3]
            num_words = len(selected_words)

            # Distribute space equally (target 9 chars)
            target_base_length = 9
            chars_per_word = max(3, target_base_length // num_words)

            # Build base slug
            word_parts = []
            for word in selected_words:
                word_parts.append(word[:chars_per_word])

            base_slug = "".join(word_parts)

            # Extend first word if space remains
            remaining = target_base_length - len(base_slug)
            if remaining > 0 and len(selected_words[0]) > chars_per_word:
                extended_first = selected_words[0][:chars_per_word + remaining]
                base_slug = extended_first + "".join(word_parts[1:])

            base_slug = base_slug[:target_base_length]

    # Add UUID suffix (5-6 chars for migration)
    available_space = max_length - len(base_slug) - 1
    uuid_len = max(5, min(6, available_space))
    uuid_suffix = secrets.token_urlsafe(uuid_len)[:uuid_len]

    return f"{base_slug}-{uuid_suffix}"[:max_length]


def cleanup_partial_state(apps, schema_editor):
    """Clean up any partial state from a previous failed migration attempt."""
    # Drop the partial index if it exists
    try:
        with schema_editor.connection.cursor() as cursor:
            cursor.execute("DROP INDEX IF EXISTS geometries_geoplace_slug_0664ea7f_like;")
    except Exception:
        # Index doesn't exist or other error, continue
        pass


def populate_slugs_fast(apps, schema_editor):
    """Populate slugs for existing GeoPlace records using bulk operations."""
    GeoPlace = apps.get_model("geometries", "GeoPlace")
    db_alias = schema_editor.connection.alias

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
        # Generate slug using simple function (no category fallback in migration)
        # At migration time, we had a single category FK, not many-to-many
        slug = generate_slug_simple(name=place.name)

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
        # First, clean up any partial state
        migrations.RunPython(cleanup_partial_state, migrations.RunPython.noop),

        # Add slug field as nullable using RunSQL (idempotent)
        migrations.RunSQL(
            sql="ALTER TABLE geometries_geoplace ADD COLUMN IF NOT EXISTS slug VARCHAR(15) NULL;",
            reverse_sql="ALTER TABLE geometries_geoplace DROP COLUMN IF EXISTS slug;"
        ),

        # Populate slugs using optimized bulk operations
        migrations.RunPython(populate_slugs_fast, migrations.RunPython.noop),

        # Update any remaining NULL slugs and make column NOT NULL and UNIQUE
        migrations.RunSQL(
            sql=[
                # Update any remaining NULL slugs (fallback MD5-based)
                """UPDATE geometries_geoplace
                   SET slug = SUBSTRING(MD5(RANDOM()::text), 1, 15)
                   WHERE slug IS NULL;""",
                # Make column NOT NULL
                "ALTER TABLE geometries_geoplace ALTER COLUMN slug SET NOT NULL;",
                # Add unique constraint
                "ALTER TABLE geometries_geoplace ADD CONSTRAINT geometries_geoplace_slug_key UNIQUE (slug);",
            ],
            reverse_sql=[
                "ALTER TABLE geometries_geoplace DROP CONSTRAINT IF EXISTS geometries_geoplace_slug_key;",
                "ALTER TABLE geometries_geoplace ALTER COLUMN slug DROP NOT NULL;",
            ]
        ),
    ]

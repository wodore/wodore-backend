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
        "hotel",
        "restaurant",
        "gasthaus",
        "gasthof",
        "berghaus",
        "berggasthaus",
        "hostel",
        "cafeteria",
        "campground",
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
                extended_first = selected_words[0][: chars_per_word + remaining]
                base_slug = extended_first + "".join(word_parts[1:])

            base_slug = base_slug[:target_base_length]

    # Add UUID suffix (5-6 chars for migration)
    available_space = max_length - len(base_slug) - 1
    uuid_len = max(5, min(6, available_space))
    uuid_suffix = secrets.token_urlsafe(uuid_len)[:uuid_len]

    return f"{base_slug}-{uuid_suffix}"[:max_length]


def cleanup_partial_state(apps, schema_editor):
    """Clean up any partial state from a previous failed migration attempt."""
    import sys

    # Drop ALL slug-related indexes that might exist from previous attempts
    # This is necessary because Django's AddField will recreate them if db_index=True
    try:
        with schema_editor.connection.cursor() as cursor:
            # First, check what indexes exist
            cursor.execute("""
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = 'geometries'
                  AND tablename = 'geoplace'
                  AND indexname LIKE '%slug%';
            """)
            existing_indexes = [row[0] for row in cursor.fetchall()]

            if existing_indexes:
                print(f"→ Found {len(existing_indexes)} slug-related indexes from previous attempts:")
                for idx in existing_indexes:
                    print(f"  - {idx}")

                # Use dynamic SQL to drop any index matching the pattern
                cursor.execute("""
                    DO $$
                    DECLARE
                        idx_name text;
                        dropped_count int := 0;
                    BEGIN
                        FOR idx_name IN
                            SELECT indexname
                            FROM pg_indexes
                            WHERE schemaname = 'geometries'
                              AND tablename = 'geoplace'
                              AND indexname LIKE '%slug%'
                        LOOP
                            EXECUTE 'DROP INDEX IF EXISTS geometries.' || quote_ident(idx_name);
                            dropped_count := dropped_count + 1;
                        END LOOP;
                        RAISE NOTICE 'Dropped % indexes', dropped_count;
                    END $$;
                """)
                print(f"✓ Dropped {len(existing_indexes)} indexes")
            else:
                print("✓ No existing slug indexes found - cleanup not needed")

    except Exception as e:
        print(f"⚠ Warning during cleanup: {e}")
        print("  Continuing with migration...")
        sys.stdout.flush()
        # If cleanup fails, continue and let the migration handle it


def populate_slugs_fast(apps, schema_editor):
    """Populate slugs for existing GeoPlace records using bulk operations with progress tracking."""
    import sys
    from django.db import connection

    GeoPlace = apps.get_model("geometries", "GeoPlace")
    db_alias = schema_editor.connection.alias

    # Get total count for progress tracking
    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM geometries_geoplace WHERE slug IS NULL")
        total_null = cursor.fetchone()[0]

    if total_null == 0:
        print("✓ No NULL slugs found - skipping population")
        return

    print(f"→ Populating {total_null} slugs...")

    batch = []
    batch_size = 1000
    processed = 0
    last_progress = 0

    # Use iterator() to avoid loading all into memory
    places = (
        GeoPlace.objects.using(db_alias)
        .filter(slug__isnull=True)
        .order_by("id")
        .iterator(chunk_size=1000)
    )

    for place in places:
        # Generate slug using simple function (no category fallback in migration)
        # At migration time, we had a single category FK, not many-to-many
        slug = generate_slug_simple(name=place.name)

        place.slug = slug
        batch.append(place)

        if len(batch) >= batch_size:
            try:
                GeoPlace.objects.using(db_alias).bulk_update(batch, ["slug"], batch_size=1000)
                processed += len(batch)
                batch = []

                # Progress reporting every 10%
                progress = (processed * 100) // total_null
                if progress > last_progress and progress % 10 == 0:
                    print(f"  Progress: {processed}/{total_null} ({progress}%)")
                    sys.stdout.flush()
                    last_progress = progress
            except Exception as e:
                print(f"✗ Error updating batch: {e}")
                raise

    if batch:
        try:
            GeoPlace.objects.using(db_alias).bulk_update(batch, ["slug"], batch_size=1000)
            processed += len(batch)
        except Exception as e:
            print(f"✗ Error updating final batch: {e}")
            raise

    print(f"✓ Successfully populated {processed}/{total_null} slugs")


def update_null_slugs(apps, schema_editor):
    """Update any remaining NULL slugs using MD5 hash with verification."""
    from django.db import connection
    import sys

    with connection.cursor() as cursor:
        # Check how many NULL slugs remain
        cursor.execute("SELECT COUNT(*) FROM geometries_geoplace WHERE slug IS NULL")
        null_count = cursor.fetchone()[0]

        if null_count == 0:
            print("✓ No NULL slugs found - skipping update")
            return

        print(f"→ Updating {null_count} remaining NULL slugs...")

        # Update NULL slugs with random MD5 hash
        cursor.execute(
            """
            UPDATE geometries_geoplace
            SET slug = SUBSTRING(MD5(RANDOM()::text), 1, 15)
            WHERE slug IS NULL;
        """
        )

        # Verify all NULLs were updated
        cursor.execute("SELECT COUNT(*) FROM geometries_geoplace WHERE slug IS NULL")
        remaining_nulls = cursor.fetchone()[0]

        if remaining_nulls > 0:
            raise Exception(
                f"CRITICAL: Failed to update {remaining_nulls} NULL slugs. "
                "Migration cannot proceed safely."
            )

        print(f"✓ Successfully updated all {null_count} NULL slugs")


def ensure_unique_slugs(apps, schema_editor):
    """Ensure all slugs are unique before adding unique constraint with verification."""
    from django.db import connection

    max_iterations = 10  # Prevent infinite loop

    with connection.cursor() as cursor:
        for iteration in range(max_iterations):
            print(f"→ Uniqueness check iteration {iteration + 1}...")

            # Check for duplicates
            cursor.execute(
                """
                SELECT COUNT(*) FROM (
                    SELECT slug, COUNT(*) as cnt
                    FROM geometries_geoplace
                    WHERE slug IS NOT NULL
                    GROUP BY slug
                    HAVING COUNT(*) > 1
                ) duplicates;
            """
            )
            duplicate_count = cursor.fetchone()[0]

            if duplicate_count == 0:
                print(f"✓ All slugs are unique!")
                break

            print(f"  Found {duplicate_count} duplicate slugs - fixing...")

            # Mark duplicates by appending ID
            cursor.execute(
                """
                WITH numbered AS (
                    SELECT
                        id,
                        slug,
                        ROW_NUMBER() OVER (PARTITION BY slug ORDER BY id) as rn
                    FROM geometries_geoplace
                    WHERE slug IS NOT NULL
                ),
                duplicates AS (
                    SELECT id, slug
                    FROM numbered
                    WHERE rn > 1
                )
                UPDATE geometries_geoplace g
                SET slug = LEFT(d.slug || '-' || g.id::text, 15)
                FROM duplicates d
                WHERE g.id = d.id;
            """
            )

            # Verify fix worked
            cursor.execute(
                """
                SELECT COUNT(*) FROM (
                    SELECT slug, COUNT(*) as cnt
                    FROM geometries_geoplace
                    WHERE slug IS NOT NULL
                    GROUP BY slug
                    HAVING COUNT(*) > 1
                ) duplicates;
            """
            )
            remaining = cursor.fetchone()[0]

            if remaining > 0:
                print(f"  Warning: Still {remaining} duplicates after iteration {iteration + 1}")
            else:
                print(f"  ✓ Fixed all duplicates in iteration {iteration + 1}")
        else:
            # This should never happen, but just in case
            raise Exception(
                f"Failed to ensure uniqueness after {max_iterations} iterations. "
                "Manual intervention required."
            )

        # Final verification
        cursor.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT slug, COUNT(*) as cnt
                FROM geometries_geoplace
                WHERE slug IS NOT NULL
                GROUP BY slug
                HAVING COUNT(*) > 1
            ) duplicates;
        """
        )
        final_duplicates = cursor.fetchone()[0]

        if final_duplicates > 0:
            raise Exception(
                f"CRITICAL: Still have {final_duplicates} duplicate slugs after all fixes. "
                "Migration cannot proceed safely."
            )

        print(f"✓ Uniqueness verified: all {final_duplicates} slugs are unique")


class Migration(migrations.Migration):

    dependencies = [
        ("geometries", "0011_update_source_id_field_and_indexes"),
    ]

    operations = [
        # First, clean up any partial state
        migrations.RunPython(cleanup_partial_state, migrations.RunPython.noop),

        # Step 1: Add slug field as nullable WITHOUT db_index to prevent duplicate indexes
        # The AlterField operation will create the UNIQUE constraint which provides both indexes
        migrations.AddField(
            model_name="geoplace",
            name="slug",
            field=models.SlugField(max_length=15, null=True, blank=True, db_index=False),
        ),

        # Step 2: Populate slugs using optimized bulk operations
        migrations.RunPython(populate_slugs_fast, migrations.RunPython.noop),

        # Step 3: Update any remaining NULL slugs
        migrations.RunPython(update_null_slugs, migrations.RunPython.noop),

        # Step 4: Ensure all slugs are unique before adding constraint
        migrations.RunPython(ensure_unique_slugs, migrations.RunPython.noop),

        # Step 5: Make slug NOT NULL and UNIQUE
        # CRITICAL: db_index=False prevents Django from creating duplicate _like indexes
        # The UNIQUE constraint already provides a B-tree index, and Django automatically
        # creates the varchar_pattern_ops index for the unique constraint
        migrations.AlterField(
            model_name="geoplace",
            name="slug",
            field=models.SlugField(max_length=15, unique=True, db_index=False),
        ),
    ]

"""Replace ``GeoPlace.parent`` with ``part_of`` relations (task 3.4).

OpenSpec ``geoplace-kinds-operations-graph`` (from draft PR #154):
hierarchy is expressed exclusively through ``part_of`` edges. The
data migration is idempotent (get_or_create per parent link); the
field removal follows in the same migration. Output-wire neutral
(verified — no API payload serialized ``parent``).
"""

from typing import Any

from django.db import migrations


def migrate_parent_to_relations(apps: Any, schema_editor: Any) -> None:
    # Raw SQL: the historical GeoPlace model's modeltrans virtual fields
    # (name_i18n etc.) can't be resolved through the ORM on fresh
    # databases — a cursor avoids the field-resolution machinery.
    Category = apps.get_model("categories", "Category")

    try:
        part_of = Category.objects.get(slug="part_of", parent__slug="relations")
    except Category.DoesNotExist:
        return  # vocabulary not seeded — nothing to migrate onto

    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO geometries_geoplacerelation
                (from_place_id, to_place_id, relation_id, confidence, extra,
                 created, modified)
            SELECT gp.id, gp.parent_id, %s, 1.0, '{}'::jsonb,
                   NOW(), NOW()
            FROM geometries_geoplace gp
            WHERE gp.parent_id IS NOT NULL
            ON CONFLICT (from_place_id, to_place_id, relation_id)
            DO NOTHING
            """,
            [part_of.pk],
        )


class Migration(migrations.Migration):
    dependencies = [
        ("geometries", "0063_geoplacerelation"),
    ]

    operations = [
        migrations.RunPython(migrate_parent_to_relations, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="geoplace",
            name="parent",
        ),
    ]

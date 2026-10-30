"""GeoPlace.kind FK — the anchoring main category (geoplace-kind-fk).

The kind becomes a stored, indexed fact: ``kind = first category
association by ``(order, slug)`` — the exact rule every consumer
derived from so far (task 1.1/1.2). The association table stays the
source of truth for classifiers/extras (D1); the FK is the
denormalized anchor, re-derived on every write path alongside
``domain``.

The ``AlterField`` on ``domain`` (verbose_name/help_text) ships in
its own migration on the base branch (#464) — this one chains onto
it.

Backfill: a single-statement UPDATE with a correlated subquery —
the per-row trigger overhead needs the lifted statement timeout
(see 0066/0072). Fine for today's ~443k rows; at the projected 5M
scale, re-estimate the timeout or chunk by pk range first.
"""

from typing import Any

import django.db.models.deletion
from django.db import migrations, models

BACKFILL_SQL = """
    UPDATE geometries_geoplace gp
    SET kind_id = (
        SELECT gpc.category_id
        FROM geometries_geoplace_category gpc
        JOIN categories_category cat ON gpc.category_id = cat.id
        WHERE gpc.geo_place_id = gp.id
        ORDER BY cat."order", cat.slug
        LIMIT 1
    )
    WHERE gp.kind_id IS NULL
"""


def backfill_kind(_apps: Any, schema_editor: Any) -> None:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SET LOCAL statement_timeout = '120s'")
        cursor.execute(BACKFILL_SQL)


def null_kind(_apps: Any, schema_editor: Any) -> None:
    with schema_editor.connection.cursor() as cursor:
        # same lifted timeout as the backfill — full-table UPDATE
        cursor.execute("SET LOCAL statement_timeout = '120s'")
        cursor.execute("UPDATE geometries_geoplace SET kind_id = NULL")


class Migration(migrations.Migration):
    dependencies = [
        ("categories", "0023_category_is_protected"),
        # chains onto the label migration (#464) — both would otherwise
        # leaf off 0072 and Django refuses multiple leaf nodes
        ("geometries", "0073_domain_verbose_label"),
    ]

    operations = [
        migrations.AddField(
            model_name="geoplace",
            name="kind",
            field=models.ForeignKey(
                blank=True,
                help_text="The anchoring main category (derived: first association by order, slug) — categories inline edits re-anchor on save",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="places_anchored",
                to="categories.category",
                verbose_name="Kind",
            ),
        ),
        migrations.RunPython(backfill_kind, null_kind),
    ]

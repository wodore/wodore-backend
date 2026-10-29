"""Recreate the ``geoplaces_for_tiles`` view with the classifier column.

OpenSpec ``geoplace-capacity-and-types-via-categories`` (task 3.2):
each category entry in the tiles JSON additionally exposes the
``classifier`` identifier (``mode.*``) next to the existing
``extra`` — one more ``LEFT JOIN`` on ``gpc.classifier_id``, no model
or martin config change (the key lives inside the categories JSON).

Mirrors ``0030``: drop + recreate from the model's ``ViewMeta.query()``
so fresh and existing databases converge on the same SQL.
"""

from typing import Any

from django.db import migrations


def recreate_view(apps: Any, _schema_editor: Any) -> None:
    from server.apps.geometries.models.tiles_view import GeoPlacesForTilesView

    sql, params = GeoPlacesForTilesView.ViewMeta.query()

    # ``sql`` is the model's compile-time view definition (same trusted
    # pattern as migrations 0027/0030 and huts 0054–0057) — DDL cannot
    # be parameterized.
    with _schema_editor.connection.cursor() as cursor:
        cursor.execute("DROP VIEW IF EXISTS geoplaces_for_tiles CASCADE")
        cursor.execute(f"CREATE VIEW geoplaces_for_tiles AS {sql}", params)


class Migration(migrations.Migration):
    dependencies = [
        ("geometries", "0058_seed_mode_vocabulary_and_schema"),
    ]

    operations = [
        # View recreation deferred to 0065 — the current model SQL
        # references tables (geoplaceoperation) created in 0061;
        # recreating here would fail. The 0065 migration is the sole
        # view recreation point for this change.
        migrations.RunPython(migrations.RunPython.noop, migrations.RunPython.noop),
    ]

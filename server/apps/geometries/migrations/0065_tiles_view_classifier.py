"""Recreate the tiles view with the classifier column.

The sole view recreation point for this change (deferred from 0059 —
the model SQL references tables created by 0061+; recreating at 0059
would fail on fresh databases). Task 3.2 + advisor P0 fix.
"""

from typing import Any

from django.db import migrations


def recreate_view(apps: Any, schema_editor: Any) -> None:
    from server.apps.geometries.models.tiles_view import GeoPlacesForTilesView

    sql, params = GeoPlacesForTilesView.ViewMeta.query()
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("DROP VIEW IF EXISTS geoplaces_for_tiles CASCADE")
        cursor.execute(f"CREATE VIEW geoplaces_for_tiles AS {sql}", params)


class Migration(migrations.Migration):
    dependencies = [
        ("geometries", "0064_replace_parent_with_relations"),
    ]

    operations = [
        migrations.RunPython(
            code=recreate_view,
            reverse_code=recreate_view,
        ),
    ]

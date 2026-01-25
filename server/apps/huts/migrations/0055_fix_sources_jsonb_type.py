# Generated manually to fix sources field type from json to jsonb
# This ensures Django JSONField can properly deserialize the data

from django.db import migrations


def create_view_from_model(apps, schema_editor):
    """Recreate the view using the updated ViewMeta from the HutsForTilesView model."""
    from server.apps.huts.models.tiles_view import HutsForTilesView

    # Get SQL from the model's ViewMeta
    sql, params = HutsForTilesView.ViewMeta.query()

    # Drop and recreate the view (cannot use CREATE OR REPLACE when changing column types)
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("DROP VIEW IF EXISTS huts_for_tiles CASCADE")
        cursor.execute(f"CREATE VIEW huts_for_tiles AS {sql}", params)


def drop_view(apps, schema_editor):
    """Drop the view."""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("DROP VIEW IF EXISTS huts_for_tiles CASCADE")


class Migration(migrations.Migration):

    dependencies = [
        ("huts", "0054_replace_tiles_view_with_viewmeta"),
    ]

    operations = [
        # Recreate the view with jsonb instead of json for sources field
        migrations.RunPython(
            code=create_view_from_model,
            reverse_code=drop_view,
        ),
    ]

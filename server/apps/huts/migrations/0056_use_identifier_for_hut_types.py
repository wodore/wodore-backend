# Generated manually to update view to use identifier instead of slug for hut types

from django.db import migrations


def create_view_from_model(apps, schema_editor):
    """Recreate the view using the updated ViewMeta from the HutsForTilesView model."""
    from server.apps.huts.models.tiles_view import HutsForTilesView

    # Get SQL from the model's ViewMeta
    sql, params = HutsForTilesView.ViewMeta.query()

    # Drop and recreate the view
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("DROP VIEW IF EXISTS huts_for_tiles CASCADE")
        cursor.execute(f"CREATE VIEW huts_for_tiles AS {sql}", params)


def drop_view(apps, schema_editor):
    """Drop the view."""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("DROP VIEW IF EXISTS huts_for_tiles CASCADE")


class Migration(migrations.Migration):

    dependencies = [
        ("huts", "0055_fix_sources_jsonb_type"),
    ]

    operations = [
        # Recreate the view with identifier instead of slug for hut types
        migrations.RunPython(
            code=create_view_from_model,
            reverse_code=drop_view,
        ),
    ]

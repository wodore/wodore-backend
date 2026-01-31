# Generated manually to update view with all standard/reduced changes

from django.db import migrations


def create_view_from_model(apps, schema_editor):
    """Recreate the view using the updated ViewMeta from the HutsForTilesView model."""
    from server.apps.huts.models.tiles_view import HutsForTilesView

    # Get SQL from the model's ViewMeta
    # Call the query() method to get the SQL and params
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
        ("huts", "0056_use_identifier_for_hut_types"),
    ]

    operations = [
        # Recreate the view with all changes:
        # - Renamed capacity_open/closed to capacity_standard/reduced
        # - Renamed type_open/closed to type_standard/reduced
        # - Added type_standard_identifier and type_reduced_identifier
        migrations.RunPython(
            code=create_view_from_model,
            reverse_code=drop_view,
        ),
    ]

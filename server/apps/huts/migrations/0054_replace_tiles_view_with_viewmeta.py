# Generated manually to use ViewMeta from model instead of hardcoded SQL
# This migration recreates the huts_for_tiles view using the ViewMeta.query() from the model

from django.db import migrations


def create_view_from_model(apps, schema_editor):
    """Create the view using the ViewMeta from the HutsForTilesView model."""
    from server.apps.huts.models.tiles_view import HutsForTilesView

    # Get SQL from the model's ViewMeta
    sql, params = HutsForTilesView.ViewMeta.query()

    # Create the view
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f"CREATE VIEW huts_for_tiles AS {sql}", params)


def drop_view(apps, schema_editor):
    """Drop the view."""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("DROP VIEW IF EXISTS huts_for_tiles CASCADE")


class Migration(migrations.Migration):

    dependencies = [
        ("huts", "0053_create_tiles_view"),
    ]

    operations = [
        # First drop the old view created by RunSQL in migration 0053
        migrations.RunSQL(
            sql="DROP VIEW IF EXISTS huts_for_tiles CASCADE;",
            reverse_sql="",  # Reverse is handled by create_view_from_model
        ),
        # Then create the view using the ViewMeta from the model
        # This way, when the model's ViewMeta changes, we can regenerate this easily
        migrations.RunPython(
            code=create_view_from_model,
            reverse_code=drop_view,
        ),
    ]

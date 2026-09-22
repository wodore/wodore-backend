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
        # The view SQL (ViewMeta.query) references categories_category.color,
        # added by categories.0013. Without this explicit dependency the
        # interleaved app order on a fresh database can run this view
        # migration first and fail with `column cat_open.color does not
        # exist`. Dependency-only change: no effect on already-migrated
        # databases.
        ("categories", "0013_remove_category_color_dark_and_more"),
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

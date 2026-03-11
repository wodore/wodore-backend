# Generated manually to create GeoPlacesForTilesView

from django.db import migrations


def create_view_from_model(apps, schema_editor):
    """Create the view using the ViewMeta from GeoPlacesForTilesView model."""
    from server.apps.geometries.models.tiles_view import GeoPlacesForTilesView

    # Get SQL from the model's ViewMeta
    # Call the query() method to get the SQL and params
    sql, params = GeoPlacesForTilesView.ViewMeta.query()

    # Create the view
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("DROP VIEW IF EXISTS geoplaces_for_tiles CASCADE")
        cursor.execute(f"CREATE VIEW geoplaces_for_tiles AS {sql}", params)


def drop_view(apps, schema_editor):
    """Drop the view."""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("DROP VIEW IF EXISTS geoplaces_for_tiles CASCADE")


class Migration(migrations.Migration):

    dependencies = [
        ("geometries", "0026_alter_geoplace_categories_and_more"),
    ]

    operations = [
        migrations.RunPython(
            code=create_view_from_model,
            reverse_code=drop_view,
        ),
    ]

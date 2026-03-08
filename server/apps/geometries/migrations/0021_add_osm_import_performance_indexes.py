# Generated manually for OSM import performance optimization

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("geometries", "0020_alter_geoplace_is_public_and_more"),
    ]

    operations = [
        # B-tree index on place_type for category filtering during import
        # Used heavily in deduplication queries that filter by category parent slug
        migrations.AddIndex(
            model_name="geoplace",
            index=models.Index(
                fields=["place_type"],
                name="geoplaces_place_type_idx",
            ),
        ),
        # Composite index for common import query pattern:
        # Filter by country + active + category, then do spatial lookup
        migrations.AddIndex(
            model_name="geoplace",
            index=models.Index(
                fields=["country_code", "is_active", "place_type"],
                name="geoplaces_country_active_type_idx",
            ),
        ),
    ]

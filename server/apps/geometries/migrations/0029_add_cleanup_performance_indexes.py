# Generated manually for cleanup query performance optimization

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("geometries", "0028_create_geoplaces_tile_function"),
    ]

    operations = [
        # Index on is_active for filtering active places during cleanup
        # Used in: GeoPlace.objects.filter(is_active=True, country_code=..., categories__in=...)
        migrations.AddIndex(
            model_name="geoplace",
            index=models.Index(
                fields=["is_active"],
                name="geoplaces_is_active_idx",
            ),
        ),
        # Composite index for GeoPlaceSourceAssociation lookup during cleanup
        # Optimizes queries filtering by organization + modified_date + geo_place
        # Used in: GeoPlaceSourceAssociation.objects.filter(
        #     organization=...,
        #     modified_date__lt=...,
        #     geo_place=OuterRef('pk'),
        #     geo_place__categories__in=...,
        # )
        migrations.AddIndex(
            model_name="geoplacesourceassociation",
            index=models.Index(
                fields=["organization", "modified_date", "geo_place"],
                name="geosa_org_modified_place_idx",
            ),
        ),
        # Index on geo_place for faster joins in cleanup query
        # This speeds up the geo_place__categories__in filter
        migrations.AddIndex(
            model_name="geoplacesourceassociation",
            index=models.Index(
                fields=["geo_place"],
                name="geosa_geo_place_idx",
            ),
        ),
    ]

# Generated manually on 2026-03-11

from django.db import migrations


def verify_geoplace_categories(apps, schema_editor):
    GeoPlace = apps.get_model("geometries", "GeoPlace")
    db_alias = schema_editor.connection.alias

    missing_qs = (
        GeoPlace.objects.using(db_alias)
        .filter(category_associations__isnull=True)
        .order_by("id")
    )
    missing_count = missing_qs.count()
    if missing_count:
        sample_ids = list(missing_qs.values_list("id", flat=True)[:5])
        raise RuntimeError(
            "GeoPlace categories migration verification failed: "
            f"{missing_count} places without categories. Sample IDs: {sample_ids}"
        )


class Migration(migrations.Migration):

    dependencies = [
        ("geometries", "0024_add_geoplace_categories_m2m"),
    ]

    operations = [
        migrations.RunPython(
            verify_geoplace_categories, reverse_code=migrations.RunPython.noop
        ),
    ]

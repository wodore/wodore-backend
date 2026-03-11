# Generated migration

from django.db import migrations, models
import django.db.models.deletion


def remove_duplicate_associations(apps, schema_editor):
    """Remove duplicate GeoPlaceSourceAssociation entries efficiently."""
    GeoPlaceSourceAssociation = apps.get_model("geometries", "GeoPlaceSourceAssociation")

    # Find and delete duplicates in batches to avoid memory issues
    # Use a more efficient approach with values() to reduce memory
    seen = set()
    duplicate_ids = []

    # Use iterator() to avoid loading all objects into memory
    for assoc in GeoPlaceSourceAssociation.objects.filter(
        source_id__isnull=False
    ).exclude(source_id="").order_by("id").iterator():
        key = (assoc.organization_id, assoc.source_id)
        if key in seen:
            duplicate_ids.append(assoc.id)
        else:
            seen.add(key)

        # Delete in batches of 1000 to avoid long transactions
        if len(duplicate_ids) >= 1000:
            GeoPlaceSourceAssociation.objects.filter(id__in=duplicate_ids).delete()
            duplicate_ids = []

    # Delete remaining duplicates
    if duplicate_ids:
        GeoPlaceSourceAssociation.objects.filter(id__in=duplicate_ids).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("organizations", "0001_initial"),
        ("geometries", "0022_remove_geoplace_geoplaces_place_type_idx_and_more"),
    ]

    operations = [
        # Remove duplicate associations using Python for better control
        migrations.RunPython(remove_duplicate_associations, migrations.RunPython.noop),
        # Remove the old incomplete unique constraint
        migrations.RunSQL(
            """
            ALTER TABLE geometries_geoplacesourceassociation
            DROP CONSTRAINT IF EXISTS geometries_geoplacesourceassociation_unique_relationships;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
        # Add the proper unique constraint that includes source_id
        migrations.AddConstraint(
            model_name="geoplacesourceassociation",
            constraint=models.UniqueConstraint(
                name="geometries_geoplacesourceassociation_unique_org_source",
                fields=["organization", "source_id"],
                condition=models.Q(source_id__isnull=False) & ~models.Q(source_id=""),
            ),
        ),
    ]

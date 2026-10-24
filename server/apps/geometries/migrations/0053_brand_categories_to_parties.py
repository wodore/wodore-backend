"""Convert brand categories to parties and drop the ``brand`` FK.

OpenSpec change ``geoplace-parties`` (tasks 2.1 + 2.2): every
``AmenityDetail.brand`` Category reference becomes a ``Party`` (slug
and localized name preserved) plus a ``GeoPlaceParty`` association with
role ``role.brand``; then the FK is removed. ``root.brand`` category
rows stay in the database for rollback safety (cleanup in a later
change).

Rollback: reversing restores the (empty) ``brand`` column — the data
lives on in the Party rows and is re-derivable. The reverse of the
conversion is therefore a no-op.
"""

from django.db import migrations


def convert_brand_to_party(apps, schema_editor):
    AmenityDetail = apps.get_model("geometries", "AmenityDetail")
    Party = apps.get_model("parties", "Party")
    GeoPlaceParty = apps.get_model("geometries", "GeoPlaceParty")
    Category = apps.get_model("categories", "Category")

    try:
        role_brand = Category.objects.get(identifier="role.brand")
    except Category.DoesNotExist:
        # Vocabulary not seeded — nothing to convert to.
        return

    for detail in AmenityDetail.objects.exclude(brand__isnull=True).select_related(
        "brand"
    ):
        category = detail.brand
        # Only the name_* translations carry over (Category also
        # translates description_*; Party translates name/note).
        i18n = {
            key: value
            for key, value in (category.i18n or {}).items()
            if key.startswith("name_")
        }
        party, _created = Party.objects.get_or_create(
            slug=category.slug,
            defaults={
                "name": category.name or category.slug.replace("_", " ").title(),
                "i18n": i18n,
            },
        )
        GeoPlaceParty.objects.get_or_create(
            geo_place_id=detail.geo_place_id, party=party, role=role_brand
        )


class Migration(migrations.Migration):

    dependencies = [
        ("geometries", "0052_seed_role_vocabulary"),
        ("parties", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(convert_brand_to_party, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="amenitydetail",
            name="brand",
        ),
    ]

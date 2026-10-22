# Generated manually — retires the plain (non-hill) outdoor basemap pair.
# The -hill variant is the product (PR #292 user decision, reaffirmed when
# stale saved selections kept rendering the outdated plain variant): the
# plain rows are deactivated so saved client selections stop resolving and
# the frontend falls back to the catalog default (wd-outdoor-base-mtk-hill,
# promoted to the visible product slot in the same change).

from django.db import migrations

RETIRED_SLUGS = ("wd-outdoor-base-mtk", "wd-outdoor-base-ofm")


def retire(apps, schema_editor):
    MapLayer = apps.get_model("basemaps", "MapLayer")
    MapLayer.objects.filter(slug__in=RETIRED_SLUGS).update(is_active=False)


def unretire(apps, schema_editor):
    MapLayer = apps.get_model("basemaps", "MapLayer")
    MapLayer.objects.filter(slug__in=RETIRED_SLUGS).update(is_active=True)


class Migration(migrations.Migration):
    dependencies = [
        ("basemaps", "0006_seed_maptoolkit_tilejson_external_entries"),
    ]

    operations = [
        migrations.RunPython(retire, unretire),
    ]

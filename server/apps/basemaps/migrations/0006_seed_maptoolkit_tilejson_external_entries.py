# Generated manually — seeds the maptoolkit TileJSON endpoints referenced
# by the mtk basemap variants as external registry entries. The daily
# verifier baselines their content hash on first run; the injector then
# content-keys the styles' TileJSON source ``url`` fields (a provider-side
# TileJSON change rotates every client's cached copy via the new ``?v=``).

from django.db import migrations

EXTERNAL_TERRAIN_SEED = (
    "https://tiles.maptoolkit.org/mtk.json",
    "https://tiles.maptoolkit.org/contours.json",
    "https://tiles.maptoolkit.org/raster_bathymetry.json",
    "https://tiles.maptoolkit.org/terrainrgb.json",
    "https://tiles.maptoolkit.org/naturalearth.json",
    "https://tiles.maptoolkit.org/rocks.json",
)


def seed_external(apps, schema_editor):
    TileAssetVersion = apps.get_model("basemaps", "TileAssetVersion")
    for key in EXTERNAL_TERRAIN_SEED:
        TileAssetVersion.objects.get_or_create(
            key=key,
            defaults={
                # Literal origin: historical models don't carry the
                # TextChoices class attribute.
                "origin": "external",
                # Empty version: not injected until the first verifier
                # run baselines the content hash.
                "version": "",
            },
        )


def unseed_external(apps, schema_editor):
    TileAssetVersion = apps.get_model("basemaps", "TileAssetVersion")
    TileAssetVersion.objects.filter(key__in=EXTERNAL_TERRAIN_SEED).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("basemaps", "0005_tile_asset_schedules_and_external_seeds"),
    ]

    operations = [
        migrations.RunPython(seed_external, unseed_external),
    ]

# Generated manually — schedules the recurring tile-asset tasks and
# seeds the external registry baseline (maptoolkit sprites referenced
# by the wd-outdoor-base-mtk fixture; openfreemap is path-versioned
# upstream and deliberately not registered).
#
# The Schedule rows are written through the HISTORICAL model
# (apps.get_model) with literal schedule-type codes — the live model
# class would query columns that may not exist yet at this point in
# the graph, and historical models don't carry custom class constants.

from django.db import migrations

WATCHER_FUNC = "server.apps.basemaps.tile_assets.run_martin_watcher"
VERIFIER_FUNC = "server.apps.basemaps.tile_assets.run_external_verifier"

SCHEDULE_MINUTES = "I"
SCHEDULE_DAILY = "D"

EXTERNAL_SEED = (
    "https://icons.maptoolkit.org/sprite",
    "https://icons.maptoolkit.org/nature~hsl_81_60_80",
    "https://icons.maptoolkit.org/water~hsl_182_65_80",
)


def create_schedules(apps, schema_editor):
    Schedule = apps.get_model("django_q", "Schedule")
    Schedule.objects.get_or_create(
        func=WATCHER_FUNC,
        defaults={
            "name": "martin_asset_watch",
            "schedule_type": SCHEDULE_MINUTES,
            "minutes": 15,
        },
    )
    Schedule.objects.get_or_create(
        func=VERIFIER_FUNC,
        defaults={
            "name": "external_asset_verify",
            "schedule_type": SCHEDULE_DAILY,
        },
    )


def remove_schedules(apps, schema_editor):
    Schedule = apps.get_model("django_q", "Schedule")
    Schedule.objects.filter(func__in=(WATCHER_FUNC, VERIFIER_FUNC)).delete()


def seed_external(apps, schema_editor):
    TileAssetVersion = apps.get_model("basemaps", "TileAssetVersion")
    for key in EXTERNAL_SEED:
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
    TileAssetVersion.objects.filter(key__in=EXTERNAL_SEED).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("basemaps", "0004_tileassetversion_tileassetversion_upd_mod_660210b3"),
        # Latest django_q migration: guarantees the schedule table has
        # its final shape (incl. 0016's intended_date_kwarg) before the
        # historical-model queries above run.
        (
            "django_q",
            "0019_alter_task_options_alter_ormq_key_alter_ormq_lock_and_more",
        ),
    ]

    operations = [
        migrations.RunPython(create_schedules, remove_schedules),
        migrations.RunPython(seed_external, unseed_external),
    ]

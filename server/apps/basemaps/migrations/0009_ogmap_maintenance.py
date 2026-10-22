# Generated manually — seeds the OpenTopoMap sample tile as an external
# registry entry (its content version rotates the OG static-map cache
# key when OTM updates its tiles) and schedules the daily OG-map
# cleanup (cards older than 30 days are deleted; requests re-render).

from django.db import migrations

VERIFY_FUNC = "server.apps.basemaps.tile_assets.run_external_verifier"
CLEANUP_FUNC = "server.apps.basemaps.tile_assets.cleanup_og_maps"

SCHEDULE_DAILY = "D"

OTM_TILE = "https://tile.opentopomap.org/10/540/357.png"


def seed_and_schedule(apps, schema_editor):
    TileAssetVersion = apps.get_model("basemaps", "TileAssetVersion")
    TileAssetVersion.objects.get_or_create(
        key=OTM_TILE,
        defaults={"origin": "external", "version": ""},
    )
    Schedule = apps.get_model("django_q", "Schedule")
    Schedule.objects.get_or_create(
        func=CLEANUP_FUNC,
        defaults={"name": "og_map_cleanup", "schedule_type": SCHEDULE_DAILY},
    )


def unseed(apps, schema_editor):
    TileAssetVersion = apps.get_model("basemaps", "TileAssetVersion")
    TileAssetVersion.objects.filter(key=OTM_TILE).delete()
    Schedule = apps.get_model("django_q", "Schedule")
    Schedule.objects.filter(func=CLEANUP_FUNC).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("basemaps", "0008_watcher_daily_backup_cadence"),
        (
            "django_q",
            "0019_alter_task_options_alter_ormq_key_alter_ormq_lock_and_more",
        ),
    ]

    operations = [
        migrations.RunPython(seed_and_schedule, unseed),
    ]

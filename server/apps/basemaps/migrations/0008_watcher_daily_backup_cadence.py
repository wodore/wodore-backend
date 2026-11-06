# Generated manually — the Martin asset watcher's recurring schedule
# drops from every 15 minutes to once daily: the primary trigger is the
# immediate run martin_sync enqueues after a successful sync (content-gated
# publication makes timing harmless), the daily pass is the backup that
# catches Martin restarts/upgrades independent of a sync.

from django.db import migrations

WATCHER_FUNC = "server.apps.basemaps.tile_assets.run_martin_watcher"

SCHEDULE_DAILY = "D"


def set_daily(apps, schema_editor):
    Schedule = apps.get_model("django_q", "Schedule")
    Schedule.objects.filter(func=WATCHER_FUNC).update(
        schedule_type=SCHEDULE_DAILY,
        minutes=None,
    )


def set_quarter_hourly(apps, schema_editor):
    Schedule = apps.get_model("django_q", "Schedule")
    Schedule.objects.filter(func=WATCHER_FUNC).update(
        schedule_type="I",
        minutes=15,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("basemaps", "0007_retire_plain_outdoor_basemap_pair"),
        ("django_q", "0019_alter_task_options_alter_ormq_key_alter_ormq_lock_and_more"),
    ]

    operations = [
        migrations.RunPython(set_daily, set_quarter_hourly),
    ]

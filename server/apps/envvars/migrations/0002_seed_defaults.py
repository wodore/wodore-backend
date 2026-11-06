"""Seed the default registry entries (maptiler-hybrid basemap key)."""

from django.db import migrations

#: (name, description) — active, empty value, env fallback on: the
#: variable resolves from the process environment (infisical) until an
#: operator stores a value in the admin.
DEFAULTS: tuple[tuple[str, str], ...] = (
    (
        "WODORE_MAPTILER_API_KEY",
        "MapTiler hybrid satellite basemap (maptiler-hybrid layer style URL)",
    ),
)


def seed(apps, schema_editor):
    EnvVar = apps.get_model("envvars", "EnvVar")
    for name, description in DEFAULTS:
        EnvVar.objects.update_or_create(
            name=name,
            defaults={
                "value": "",
                "env_fallback": True,
                "is_active": True,
                "description": description,
            },
        )


def unseed(apps, schema_editor):
    EnvVar = apps.get_model("envvars", "EnvVar")
    EnvVar.objects.filter(name__in=[name for name, _ in DEFAULTS]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("envvars", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]

"""Seed the URL-origin registry entries (admin-editable deploy URLs).

Empty values + env fallback: each row resolves to the Django setting
(``MARTIN_TILE_URL`` / ``IMAGOR_URL`` / ``BACKEND_DOMAIN``), which
itself is env/infisical-driven — behavior is unchanged until an
operator stores a value in the admin (stored value wins).
"""

from django.db import migrations

#: (name, description) — active, empty value, env fallback on.
DEFAULTS: tuple[tuple[str, str], ...] = (
    (
        "MARTIN_TILE_URL",
        (
            "Public tile origin (tile-router/Martin; CDN in staging/prod) "
            "— replaces {TILE_SERVER_URL} in served map styles"
        ),
    ),
    (
        "IMAGOR_URL",
        (
            "Public imagor image origin — prefixed onto signed image "
            "URLs in API responses"
        ),
    ),
    (
        "BACKEND_DOMAIN",
        ("Backend public base URL — og watermark URLs and RFC 9457 problem-type URIs"),
    ),
)


def seed(apps, schema_editor):
    EnvVar = apps.get_model("envvars", "EnvVar")
    for name, description in DEFAULTS:
        # get_or_create, not update_or_create: a replay (fake-back +
        # forward, restored DB with reset migration state) must never
        # clobber a value an operator administered in the admin.
        EnvVar.objects.get_or_create(
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
        ("envvars", "0003_alter_envvar_name"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]

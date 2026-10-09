"""Seed the basic curated lists (openspec: icon-library).

Creates the default ``activities`` shortlist and attaches the seeded
activity icons (whichever exist — imports may run after this
migration). Further lists (overlays, basemaps markers, ...) are
created manually in the admin.
"""

from django.db import migrations

from server.apps.symbols.icon_data import CURATED_ACTIVITY_SLUGS

DEFAULT_LIST = {"slug": "activities", "name": "Activities"}


def seed_activities_list(apps, schema_editor):
    Icon = apps.get_model("symbols", "Icon")
    IconCuratedList = apps.get_model("symbols", "IconCuratedList")
    IconCuratedListEntry = apps.get_model("symbols", "IconCuratedListEntry")

    curated_list = IconCuratedList.objects.filter(slug=DEFAULT_LIST["slug"]).first()
    if curated_list is None:
        curated_list = IconCuratedList.objects.create(**DEFAULT_LIST)
    icons = Icon.objects.filter(
        pack__slug="fluent-emoji", slug__in=CURATED_ACTIVITY_SLUGS
    )
    for icon in icons:
        IconCuratedListEntry.objects.get_or_create(curated_list=curated_list, icon=icon)


def unseed(apps, schema_editor):
    IconCuratedList = apps.get_model("symbols", "IconCuratedList")
    IconCuratedList.objects.filter(slug=DEFAULT_LIST["slug"]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("symbols", "0009_icon_curated_lists"),
    ]

    operations = [
        migrations.RunPython(seed_activities_list, unseed),
    ]

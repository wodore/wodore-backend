"""Seed the ``season`` category vocabulary for category associations.

Creates the ``season`` parent category with children ``winter_room``,
``self_service``, ``year_round``, ``closed``, and ``summer_only`` —
active, ordered, slug-stable. Idempotent: re-running (or re-applying
on a partially seeded database) get_or_creates and changes nothing.

Mirrors ``0052_seed_role_vocabulary`` (OpenSpec
``geoplace-capacity-and-types-via-categories``): the base ``name``
field carries the default-language (German) value; the English
translation lives in the ``i18n`` JSON column as ``name_en``
(modeltrans storage — there are no per-language columns). The
computed ``identifier`` column is set explicitly — data migrations
create rows through historical models, so computedfields never fires
(categories' 0006 precedent).

Reverse removes only the seeded rows; deletion is blocked by RESTRICT
while ``GeoPlaceCategory`` rows reference them (correct rollback
semantics — roll back associations first).
"""

from typing import Any

from django.db import migrations
from django.db.models import Case, Value, When

SEASON_CHILDREN = [
    # slug, name (de, modeltrans source language), name_en, order
    ("winter_room", "Winterraum", "Winter room", 10),
    ("self_service", "Selbstversorger", "Self-service", 20),
    ("year_round", "Ganzjährig", "Year-round", 30),
    ("closed", "Geschlossen", "Closed", 40),
    ("summer_only", "Nur Sommer", "Summer only", 50),
]
SEASON_SLUGS = [slug for slug, _, _, _ in SEASON_CHILDREN]


def seed(apps: Any, _schema_editor: Any) -> None:
    Category = apps.get_model("categories", "Category")
    parent, _created = Category.objects.get_or_create(
        slug="season",
        parent=None,
        defaults={
            "name": "Saison",
            "i18n": {"name_en": "Season"},
            "order": 50,
            "is_active": True,
        },
    )
    for slug, name, name_en, order in SEASON_CHILDREN:
        Category.objects.get_or_create(
            slug=slug,
            parent=parent,
            defaults={
                "name": name,
                "i18n": {"name_en": name_en},
                "order": order,
                "is_active": True,
            },
        )

    # Historical models bypass computedfields — the ``identifier``
    # column stays empty unless set explicitly (categories' 0006
    # migration exists for exactly this). Unconditional update keeps
    # the seed self-healing on re-run.
    Category.objects.filter(pk=parent.pk).update(identifier="root.season")
    Category.objects.filter(parent=parent, slug__in=SEASON_SLUGS).update(
        identifier=Case(
            *[When(slug=slug, then=Value(f"season.{slug}")) for slug in SEASON_SLUGS]
        )
    )


def unseed(apps: Any, _schema_editor: Any) -> None:
    Category = apps.get_model("categories", "Category")
    Category.objects.filter(slug__in=SEASON_SLUGS, parent__slug="season").delete()
    Category.objects.filter(slug="season", parent=None).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("categories", "0021_category_created_category_modified_and_more"),
        ("geometries", "0056_remove_brand_categories"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]

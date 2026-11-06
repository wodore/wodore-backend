"""Seed the ``mode`` vocabulary and the accommodation extra schema.

OpenSpec ``geoplace-capacity-and-types-via-categories`` (revised
design): the operating-mode vocabulary for category associations —
parent ``mode`` with children ``standard`` and ``reduced`` (these map
1:1 onto the availability tiles' ``dN_type`` classification) — plus
the initial ``CategoryExtraSchema`` on the ``accommodation`` parent
describing the association ``extra`` key ``capacity`` (one mode = one
association = its own capacity; values the source does not publish
are omitted, never ``null``).

The schema is seeded once from code; afterwards it is
admin-manageable (``Organization.props_schema`` parity — evolve
additively: new optional keys like water/heating are safe).

Mirrors ``0052_seed_role_vocabulary``: slug-stable, ordered, active;
the base ``name`` carries the German source value with English on the
``i18n`` column; the computed ``identifier`` column is set explicitly
(historical models bypass computedfields — categories' 0006
precedent). Idempotent on re-run.

Reverse removes only the seeded rows; ``mode`` children are blocked
by RESTRICT while associations reference them (roll back associations
first) and the schema row likewise.
"""

from typing import Any

from django.db import migrations
from django.db.models import Case, Value, When

MODE_CHILDREN = [
    # slug, name (de, modeltrans source language), name_en, order
    ("standard", "Standardbetrieb", "Standard operation", 10),
    ("reduced", "Reduziert", "Reduced operation", 20),
]
MODE_SLUGS = [slug for slug, _, _, _ in MODE_CHILDREN]

#: Initial accommodation extra schema — one capacity per mode
#: association, non-negative when present, never ``null`` (omitted).
ACCOMMODATION_EXTRA_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "capacity": {
            "type": ["integer", "null"],
            "minimum": 0,
            "title": "Capacity",
            "description": "Bed capacity of this operation mode",
        }
    },
    "additionalProperties": True,
}


def seed(apps: Any, _schema_editor: Any) -> None:
    Category = apps.get_model("categories", "Category")
    CategoryExtraSchema = apps.get_model("geometries", "CategoryExtraSchema")

    parent, _created = Category.objects.get_or_create(
        slug="mode",
        parent=None,
        defaults={
            "name": "Betriebsmodus",
            "i18n": {"name_en": "Operation mode"},
            "order": 50,
            "is_active": True,
        },
    )
    for slug, name, name_en, order in MODE_CHILDREN:
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

    # Historical models bypass computedfields — set identifiers
    # explicitly, unconditional so a partial seed self-heals
    # (jsonb update via Case per slug — see 0052).
    Category.objects.filter(pk=parent.pk).update(identifier="root.mode")
    Category.objects.filter(parent=parent, slug__in=MODE_SLUGS).update(
        identifier=Case(
            *[When(slug=slug, then=Value(f"mode.{slug}")) for slug in MODE_SLUGS]
        )
    )

    # Initial extra schema on the accommodation parent (children
    # inherit through the one-level fallback).
    accommodation = Category.objects.filter(
        slug="accommodation", parent__isnull=True
    ).first()
    if accommodation is not None:
        CategoryExtraSchema.objects.update_or_create(
            category=accommodation,
            defaults={"schema": ACCOMMODATION_EXTRA_SCHEMA},
        )


def unseed(apps: Any, _schema_editor: Any) -> None:
    Category = apps.get_model("categories", "Category")
    CategoryExtraSchema = apps.get_model("geometries", "CategoryExtraSchema")

    CategoryExtraSchema.objects.filter(
        category__slug="accommodation", category__parent__isnull=True
    ).delete()
    Category.objects.filter(slug__in=MODE_SLUGS, parent__slug="mode").delete()
    Category.objects.filter(slug="mode", parent=None).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("categories", "0021_category_created_category_modified_and_more"),
        ("geometries", "0057_category_mode_and_extra_schema"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]

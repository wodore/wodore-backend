"""Seed the ``role`` category vocabulary for party associations.

Creates the ``role`` parent category with children ``operator``,
``brand``, ``owner``, and ``source`` — active, ordered, slug-stable.
Idempotent: re-running (or re-applying on a partially seeded database)
get_or_creates and changes nothing.

Names: the base ``name`` field carries the default-language (German)
value; the English translation lives in the ``i18n`` JSON column as
``name_en`` (modeltrans storage — there are no per-language columns).

Reverse removes only the seeded rows; deletion is blocked by RESTRICT
while ``GeoPlaceParty`` rows reference them (correct rollback
semantics — roll back associations first).
"""

from django.db import migrations
from django.db.models import Case, Value, When

ROLE_CHILDREN = [
    # slug, name (de, modeltrans source language), name_en, order
    ("operator", "Betreiber", "Operator", 10),
    ("brand", "Marke", "Brand", 20),
    ("owner", "Eigentümer", "Owner", 30),
    ("source", "Quelle", "Source", 40),
]
ROLE_SLUGS = [slug for slug, _, _, _ in ROLE_CHILDREN]


def seed(apps, schema_editor):
    Category = apps.get_model("categories", "Category")
    parent, _created = Category.objects.get_or_create(
        slug="role",
        parent=None,
        defaults={
            "name": "Rolle",
            "i18n": {"name_en": "Role"},
            "order": 50,
            "is_active": True,
        },
    )
    for slug, name, name_en, order in ROLE_CHILDREN:
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
    Category.objects.filter(pk=parent.pk).update(identifier="root.role")
    Category.objects.filter(parent=parent, slug__in=ROLE_SLUGS).update(
        identifier=Case(
            *[When(slug=slug, then=Value(f"role.{slug}")) for slug in ROLE_SLUGS]
        )
    )


def unseed(apps, schema_editor):
    Category = apps.get_model("categories", "Category")
    Category.objects.filter(slug__in=ROLE_SLUGS, parent__slug="role").delete()
    Category.objects.filter(slug="role", parent=None).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("categories", "0021_category_created_category_modified_and_more"),
        ("geometries", "0051_geoplaceparty_geoplaceparty_upd_mod_07c6bf81"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]

"""Mark code-coupled vocabulary categories as protected.

OpenSpec ``geoplace-kinds-operations-graph`` (task 1.2): seeded
vocabulary that code couples to by slug — classifier vocabularies
(mode.*, role.*), the kind root parents (the taxonomy anchors the
kind registry resolves against), and the uri-kind roots — becomes
``is_protected``: deletion blocked in admin/model validation, names/
colors/symbols freely editable.

Idempotent: a plain conditional update, safe to re-run.
"""

from typing import Any

from django.db import migrations

#: Root parents the kind registry pins (kinds.py PLACE_KINDS).
KIND_ROOTS = [
    "accommodation",
    "tourism",
    "sport",
    "shopping",
    "food_supply",
    "restaurant",
    "groceries",
    "services",
    "finance",
    "health_and_emergency",
    "outdoor_services",
    "utilities",
    "automotive",
    "meteo",
    "availability",
    "transport",
    "administrative",
    "populated_place",
    "terrain",
    "hydrographic",
]

#: Classifier / uri vocabularies (whole subtrees under these roots).
VOCABULARY_ROOTS = ["mode", "role", "external_link", "link_type"]


def mark_protected(apps: Any, _schema_editor: Any) -> None:
    Category = apps.get_model("categories", "Category")

    roots = set(KIND_ROOTS) | set(VOCABULARY_ROOTS) | {"relations"}
    Category.objects.filter(slug__in=roots, parent__isnull=True).update(
        is_protected=True
    )
    # vocabulary children (mode.standard, role.operator, uri kinds, …)
    Category.objects.filter(
        parent__slug__in=VOCABULARY_ROOTS + ["relations"]
    ).update(is_protected=True)


def unmark_protected(apps: Any, _schema_editor: Any) -> None:
    Category = apps.get_model("categories", "Category")
    Category.objects.filter(is_protected=True).update(is_protected=False)


class Migration(migrations.Migration):
    dependencies = [
        ("categories", "0022_category_is_protected"),
        ("geometries", "0059_tiles_view_classifier"),
    ]

    operations = [
        migrations.RunPython(mark_protected, unmark_protected),
    ]

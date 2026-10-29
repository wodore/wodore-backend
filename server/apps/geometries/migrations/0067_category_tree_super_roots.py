"""Seed the map category tree: namespace root, super-roots, contracts.

OpenSpec ``geoplace-category-tree`` (task 1.2):

* ``map`` namespace root (parentless) separates map categories from
  vocabulary trees (``mode.*``, ``role.*``, ``relations.*`` … stay
  parentless).
* Super-roots ``amenity`` / ``admin`` / ``natural`` under ``map`` —
  the kind_slug derivation walks kind → contract group → super-root →
  map (4 levels); identifiers stay 2-level (direct-parent based, so
  ``hut`` keeps ``accommodation.hut``).
* The ~20 contract-group roots re-parent under their super-root.
  Historical models do not run computed-field signals — the stored
  ``identifier`` column updates manually here (children keep their
  identifiers: their parent slug is unchanged).
* ``CategoryKindContract`` rows seed from the PLACE_KINDS registry
  (kinds.py — inline copy here, migrations stay self-contained):
  accommodation carries mode classifiers, operations + seasonality;
  every other group starts with the empty contract.
* Super-roots and the map root are ``is_protected`` (slug + parent
  readonly); contract groups stay editable.

Idempotent: get_or_create / guarded updates throughout.
"""

from typing import Any

from django.db import migrations

#: Contract-group slug → super-root slug (kinds.py PLACE_KINDS copy).
SUPER_ROOT_ASSIGNMENT: dict[str, str] = {
    "accommodation": "amenity",
    "tourism": "amenity",
    "sport": "amenity",
    "shopping": "amenity",
    "food_supply": "amenity",
    "restaurant": "amenity",
    "groceries": "amenity",
    "services": "amenity",
    "finance": "amenity",
    "health_and_emergency": "amenity",
    "outdoor_services": "amenity",
    "utilities": "amenity",
    "automotive": "amenity",
    "meteo": "amenity",
    "availability": "amenity",
    "transport": "amenity",
    "administrative": "admin",
    "populated_place": "admin",
    "terrain": "natural",
    "hydrographic": "natural",
}

#: Contract-group slug → seed contract (kinds.py PLACE_KINDS copy):
#: classifier vocabulary root slugs, has_operations, has_seasonality.
CONTRACT_SEED: dict[str, tuple[tuple[str, ...], bool, bool]] = {
    "accommodation": (("mode",), True, True),
}


def seed_tree(apps: Any, _schema_editor: Any) -> None:
    Category = apps.get_model("categories", "Category")
    Contract = apps.get_model("geometries", "CategoryKindContract")

    # 1. Namespace root + super-roots (identifier set manually —
    #    historical models skip computed-field signals).
    map_root, _ = Category.objects.get_or_create(
        slug="map",
        parent=None,
        defaults={
            "identifier": "root.map",
            "name": "Map",
            "is_protected": True,
            "order": 0,
        },
    )
    super_roots: dict[str, Any] = {}
    for slug in ("amenity", "admin", "natural"):
        super_roots[slug], _ = Category.objects.get_or_create(
            slug=slug,
            parent=map_root,
            defaults={
                "identifier": f"map.{slug}",
                "name": slug.replace("_", " ").title(),
                "is_protected": True,
                "order": 0,
            },
        )

    # 2. Re-parent contract groups under their super-root + refresh
    #    their stored identifiers (children are unaffected).
    for group_slug, super_slug in SUPER_ROOT_ASSIGNMENT.items():
        super_root = super_roots[super_slug]
        updated = Category.objects.filter(
            slug=group_slug, parent=None
        ).update(parent=super_root, identifier=f"{super_slug}.{group_slug}")
        # Stray group already re-parented (idempotent re-run): refresh
        # its identifier only when it sits under the wrong identifier.
        if not updated:
            Category.objects.filter(
                slug=group_slug, parent=super_root
            ).exclude(identifier=f"{super_slug}.{group_slug}").update(
                identifier=f"{super_slug}.{group_slug}"
            )

    # 3. Seed kind contracts from the registry copy.
    for group_slug, (classifier_slugs, has_ops, has_season) in CONTRACT_SEED.items():
        group = Category.objects.filter(
            slug=group_slug, parent__slug=SUPER_ROOT_ASSIGNMENT[group_slug]
        ).first()
        if group is None:
            continue
        contract, _ = Contract.objects.get_or_create(
            category=group,
            defaults={
                "has_operations": has_ops,
                "has_seasonality": has_season,
            },
        )
        for vocab_slug in classifier_slugs:
            vocab_root = Category.objects.filter(
                slug=vocab_slug, parent=None
            ).first()
            if vocab_root is not None:
                contract.allowed_classifiers.add(vocab_root)


def unseed_tree(apps: Any, _schema_editor: Any) -> None:
    Category = apps.get_model("categories", "Category")
    Contract = apps.get_model("geometries", "CategoryKindContract")

    Contract.objects.all().delete()
    # Re-parent contract groups back to the root level.
    for group_slug in SUPER_ROOT_ASSIGNMENT:
        Category.objects.filter(slug=group_slug).update(
            parent=None, identifier=f"root.{group_slug}"
        )
    # Remove super-roots + map root.
    Category.objects.filter(slug__in=["amenity", "admin", "natural"]).delete()
    Category.objects.filter(slug="map", parent=None).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("geometries", "0066_categorykindcontract_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_tree, unseed_tree),
    ]

"""Remove the legacy ``root.brand`` category subtree (brand-category-cleanup).

OpenSpec change ``brand-category-cleanup``: geoplaces migration 0053
(converted every ``AmenityDetail.brand`` into a Party + ``role.brand``
association) deliberately kept the ``root.brand`` category subtree for
rollback safety. That window has passed — nothing references the
subtree anymore (the OSM import mints parties since #415).

``GeoPlaceCategory.category`` is RESTRICT, so place associations to
``brand.*`` categories are deleted first (superseded by the party
associations); ``root.delete()`` then runs the full deletion Collector
(cascades, SET NULL updates, RESTRICT checks) — with every default
ordering cleared on the historical registry for the duration:
the Collector compiles candidate querysets with their model's
``Meta.ordering``, and ordering by a foreign-key NAME expands into
the related model's ordering — GeoPlace's ``Lower("name_i18n")``
(the staging 0056 crash), a modeltrans field that does not exist at
migration state (the 0054/0003 lesson class). Deletion never depends
on ordering (the Collector batches by pk), so clearing it changes
nothing but the compile hazard.

Idempotent (subtree absent → no-op). Reverse is a no-op: the brand
categories were minted by the legacy OSM import on the fly and are not
re-derivable — the Party rows carry the names.
"""

from typing import Any

from django.db import migrations


def remove_brand_categories(apps: Any, _schema_editor: Any) -> None:
    Category = apps.get_model("categories", "Category")
    GeoPlaceCategory = apps.get_model("geometries", "GeoPlaceCategory")

    root = Category.objects.filter(identifier="root.brand").order_by("pk").first()
    if root is None:
        return  # already cleaned / fresh database

    # The subtree is flat by construction (0053 minted ``brand.<slug>``
    # leaves, one level); a grandchild level with associations would
    # RESTRICT-block loudly (advisor review finding 6).
    category_ids = list(root.children.order_by("pk").values_list("id", flat=True)) + [
        root.id
    ]

    # Legacy place associations (superseded by role.brand party
    # associations from 0053) — includes associations to the root
    # itself, which would otherwise RESTRICT the delete below.
    deleted, _ = (
        GeoPlaceCategory.objects.filter(category_id__in=category_ids)
        .order_by("pk")
        .delete()
    )

    # Full-ORM delete, with every default ordering on the historical
    # registry cleared for the duration: the deletion Collector
    # compiles its candidate querysets (RESTRICT / SET_NULL / CASCADE
    # checks) with each model's Meta.ordering, and ordering by a
    # foreign-key name expands into the related model's ordering —
    # GeoPlace's Lower("name_i18n"), unresolvable at migration state.
    # Deletion never depends on ordering (batches are keyed by pk), so
    # this only removes the compile hazard; ``finally`` restores the
    # registry untouched even on a crash-and-rollback.
    saved_orderings = {model: model._meta.ordering for model in apps.get_models()}
    for model in saved_orderings:
        model._meta.ordering = ()
    try:
        root.delete()  # children cascade via Category.parent
    finally:
        for model, ordering in saved_orderings.items():
            model._meta.ordering = ordering

    print(
        f"brand-category-cleanup: removed the root.brand subtree "
        f"({deleted} place associations)",
        flush=True,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("categories", "0021_category_created_category_modified_and_more"),
        ("geometries", "0055_amenity_phones_to_links"),
        ("parties", "0003_party_extra_and_slug_remint"),
    ]

    operations = [
        migrations.RunPython(remove_brand_categories, migrations.RunPython.noop),
    ]

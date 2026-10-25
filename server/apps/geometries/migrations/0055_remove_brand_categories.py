"""Remove the legacy ``root.brand`` category subtree (brand-category-cleanup).

OpenSpec change ``brand-category-cleanup``: geoplaces migration 0053
(converted every ``AmenityDetail.brand`` into a Party + ``role.brand``
association) deliberately kept the ``root.brand`` category subtree for
rollback safety. That window has passed — nothing references the
subtree anymore (the OSM import mints parties since #415).

``GeoPlaceCategory.category`` is RESTRICT, so place associations to
``brand.*`` categories are deleted first (superseded by the party
associations); the parent delete then cascades the children.

Idempotent (subtree absent → no-op). Reverse is a no-op: the brand
categories were minted by the legacy OSM import on the fly and are not
re-derivable — the Party rows carry the names.
"""

from typing import Any

from django.db import migrations


def remove_brand_categories(apps: Any, _schema_editor: Any) -> None:
    Category = apps.get_model("categories", "Category")
    GeoPlaceCategory = apps.get_model("geometries", "GeoPlaceCategory")

    root = (
        Category.objects.filter(identifier="root.brand").order_by("pk").first()
    )
    if root is None:
        return  # already cleaned / fresh database

    # Legacy place associations (superseded by role.brand party
    # associations from 0053) — includes associations to the root
    # itself, which would otherwise RESTRICT the delete below.
    category_ids = list(root.children.values_list("id", flat=True)) + [root.id]
    deleted, _ = GeoPlaceCategory.objects.filter(
        category_id__in=category_ids
    ).delete()

    root.delete()  # children cascade via Category.parent

    print(
        f"brand-category-cleanup: removed the root.brand subtree "
        f"({deleted} place associations)",
        flush=True,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("categories", "0021_category_created_category_modified_and_more"),
        ("geometries", "0054_alter_geoplace_slug_and_more"),
        ("parties", "0003_party_dedup_key_and_slug_remint"),
    ]

    operations = [
        migrations.RunPython(remove_brand_categories, migrations.RunPython.noop),
    ]

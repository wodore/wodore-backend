"""Align the legacy ``resta`` category with the ``restaurant`` icon rename.

The accommodation icon pack renamed its icon ``resta`` -> ``restaurant``
(#468); the category slug follows. Three historical shapes:

- fresh DBs carry no ``resta`` row — nothing happens;
- HutType-era DBs carry only ``resta`` — plain slug rename;
- DBs carrying BOTH ``resta`` and a sibling ``restaurant`` under the
  same parent (staging: ``accommodation.resta`` id 100 next to
  ``accommodation.restaurant`` id 136) — a plain rename dies on
  ``unique_slug_per_parent``. MERGE instead: re-point every reference
  at the surviving ``restaurant`` row, then delete the legacy row.

Re-pointed references (RESTRICT would block the delete, CASCADE would
silently drop rows, SET_NULL would silently degrade data):
``GeoPlaceCategory`` associations (deduped per (place, classifier) —
the unique constraint must hold), ``GeoPlace.kind``,
``Hut.hut_type_open/closed``, ``CategoryExtraSchema`` (OneToOne — the
target's own row wins, the legacy row is dropped),
``MapLayerCategory`` links (deduped per (layer, use) —
``unique_layer_category_use``), ``Category`` children (re-parented; a
slug collision raises — merge manually rather than cascade-delete),
``Category.default``, geonames ``Feature.category``, basemaps legend
sections, licenses.

The linked ``resta`` SYMBOLS retire (``is_active=False``) in every
case — ``category_sync_assets`` relinks the surviving category; no
step here depends on symbol state.

Reverse: best-effort. The plain rename restores by renaming back; a
MERGE is forward-only (which references came from ``resta`` is lost)
— reverse leaves merged DBs on ``restaurant``.
"""

from typing import Any

from django.db import migrations


def _merge_resta_into_restaurant(resta: Any, target: Any, apps: Any) -> None:
    """Re-point every reference from ``resta`` to ``target``, delete ``resta``."""
    Category = apps.get_model("categories", "Category")
    CategoryExtraSchema = apps.get_model("geometries", "CategoryExtraSchema")
    Feature = apps.get_model("external_geonames", "Feature")
    GeoPlace = apps.get_model("geometries", "GeoPlace")
    GeoPlaceCategory = apps.get_model("geometries", "GeoPlaceCategory")
    Hut = apps.get_model("huts", "Hut")
    License = apps.get_model("licenses", "License")
    MapLayerCategory = apps.get_model("basemaps", "MapLayerCategory")
    MapLegendSection = apps.get_model("basemaps", "MapLegendSection")

    # Place associations: re-point unless the target already carries
    # the same (place, classifier) pair — the (geo_place, category,
    # classifier) unique constraint would reject the duplicate row.
    target_pairs = {
        (assoc.geo_place_id, assoc.classifier_id)
        for assoc in GeoPlaceCategory.objects.filter(category=target)
    }
    reprice_ids: list[int] = []
    drop_ids: list[int] = []
    for assoc in GeoPlaceCategory.objects.filter(category=resta):
        key = (assoc.geo_place_id, assoc.classifier_id)
        (drop_ids if key in target_pairs else reprice_ids).append(assoc.pk)
    GeoPlaceCategory.objects.filter(pk__in=drop_ids).delete()
    GeoPlaceCategory.objects.filter(pk__in=reprice_ids).update(category=target)

    GeoPlace.objects.filter(kind=resta).update(kind=target)
    Hut.objects.filter(hut_type_open=resta).update(hut_type_open=target)
    Hut.objects.filter(hut_type_closed=resta).update(hut_type_closed=target)

    # Extra schemas: OneToOne per category — the target's own row
    # wins, a legacy row under resta is dropped rather than moved.
    if CategoryExtraSchema.objects.filter(category=target).exists():
        CategoryExtraSchema.objects.filter(category=resta).delete()
    else:
        CategoryExtraSchema.objects.filter(category=resta).update(category=target)

    # Map layer links: unique (layer, category, use) — same dedupe.
    target_uses = {
        (link.layer_id, link.use)
        for link in MapLayerCategory.objects.filter(category=target)
    }
    keep_links: list[int] = []
    drop_links: list[int] = []
    for link in MapLayerCategory.objects.filter(category=resta):
        (drop_links if (link.layer_id, link.use) in target_uses else keep_links).append(
            link.pk
        )
    MapLayerCategory.objects.filter(pk__in=drop_links).delete()
    MapLayerCategory.objects.filter(pk__in=keep_links).update(category=target)

    # Children: re-parent to the target. A slug collision means a
    # parallel child exists — fail loudly (deleting resta would
    # CASCADE-delete the child instead of merging it).
    for child in Category.objects.filter(parent=resta):
        if Category.objects.filter(parent=target, slug=child.slug).exists():
            msg = (
                f"Cannot merge resta#{resta.pk} into restaurant#{target.pk}: "
                f"child slug collision on '{child.slug}' — merge manually."
            )
            raise RuntimeError(msg)
        child.parent_id = target.pk
        child.save(update_fields=["parent"])

    Category.objects.filter(default=resta).update(default=target)
    Feature.objects.filter(category=resta).update(category=target)
    MapLegendSection.objects.filter(category=resta).update(category=target)
    License.objects.filter(category=resta).update(category=target)

    resta.delete()


def rename_resta_to_restaurant(apps: Any, schema_editor: Any) -> None:
    Category = apps.get_model("categories", "Category")
    Symbol = apps.get_model("symbols", "Symbol")

    for resta in list(Category.objects.filter(slug="resta")):
        target = (
            Category.objects.filter(slug="restaurant", parent_id=resta.parent_id)
            .exclude(pk=resta.pk)
            .first()
        )
        if target is None:
            # no sibling restaurant: the historical plain rename
            resta.slug = "restaurant"
            resta.save(update_fields=["slug"])
        else:
            # both exist: merge (staging shape) — a plain rename would
            # violate unique_slug_per_parent
            _merge_resta_into_restaurant(resta, target, apps)

    # The linked resta symbols are retired (is_active=False) so the
    # stale slug stops being served; category_sync_assets relinks the
    # surviving category to the existing restaurant symbols
    # (slug+style reuse) — independent of the merge above.
    Symbol.objects.filter(slug="resta").update(is_active=False)


def rename_restaurant_to_resta(apps: Any, schema_editor: Any) -> None:
    Category = apps.get_model("categories", "Category")
    Symbol = apps.get_model("symbols", "Symbol")
    # Best-effort reverse of the plain rename only: rename the
    # accommodation restaurant back when no resta sibling exists. A
    # merged resta row is gone — merged references stay on
    # restaurant (forward-only, see module docstring).
    for restaurant in Category.objects.filter(
        slug="restaurant", parent__slug="accommodation"
    ):
        if not Category.objects.filter(
            slug="resta", parent_id=restaurant.parent_id
        ).exists():
            restaurant.slug = "resta"
            restaurant.save(update_fields=["slug"])
    Symbol.objects.filter(slug="resta").update(is_active=True)


class Migration(migrations.Migration):
    dependencies = [
        ("categories", "0023_category_is_protected"),
    ]

    operations = [
        migrations.RunPython(rename_resta_to_restaurant, rename_restaurant_to_resta),
    ]

"""Transport becomes its own domain; kind slugs follow Transitland names.

Owner decision (post-#454 review): the transport contract group leaves
the ``amenity`` super-root for its OWN ``transport`` domain — the tree
becomes ``map → transport → transport → kinds`` and the sprite path
``transport.transport.<kind>`` (martin_sync derives names from the live
tree). The route-mode kind slugs adopt Transitland's basic route type
names (https://www.transit.land/documentation/rest-api — the GTFS codes
stay pinned in each kind's ``extra.gtfs_route_type`` and in
``seed_lib.TRANSPORT_MODES``):

    train_station → rail      bus_stop     → bus
    metro_station → metro     tram_stop    → tram
    cable_car     → cablecar

``ferry``, ``gondola``, ``funicular``, ``trolleybus`` and ``monorail``
already match; ``airport``/``parking``/``bus_station`` are OSM place
kinds, not route types — unchanged.

In-place renames/re-parents keep pks, so ``GeoPlace.kind``, hut-era
FKs and category links survive untouched. Derived state that
historical models do NOT recompute is updated manually (same doctrine
as 0067/0024):

* ``identifier`` (computedfields) — super-root, group, renamed kinds;
* ``geometries_geoplace.domain`` — the stored super-root slug of every
  place anchored on the transport group/kinds flips ``amenity`` →
  ``transport`` (the column is derived on write; this catches rows
  written before the move).

A pre-existing stray child of ``map`` named ``transport`` (seen on
staging: empty, no symbols, no children) is promoted to the super-root
instead of colliding with ``unique_slug_per_parent``.

Reverse: best-effort. Renames and the re-parent go back (guarded the
same way); places keep their derived ``domain`` (re-derived on next
write); the super-root stays behind — a harmless protected vocabulary
row, mirroring 0067's reverse doctrine.
"""

from typing import Any

from django.db import migrations

#: transport kind slug → Transitland basic route type name.
KIND_RENAMES: dict[str, str] = {
    "train_station": "rail",
    "bus_stop": "bus",
    "metro_station": "metro",
    "tram_stop": "tram",
    "cable_car": "cablecar",
}


def _identifier(parent: Any, slug: str) -> str:
    """The computed ``Category.identifier`` expression, inlined.

    Historical models skip computed-field signals (0067 doctrine):
    writes that move ``slug``/``parent`` must update ``identifier``
    explicitly.
    """
    return f"{parent.slug}.{slug}" if parent is not None else f"root.{slug}"


def _rename(category: Any, slug: str) -> None:
    """Slug rename carrying the computed identifier along."""
    category.slug = slug
    category.identifier = _identifier(category.parent, slug)
    category.save(update_fields=["slug", "identifier"])


def seed_transport_domain(apps: Any, _schema_editor: Any) -> None:
    Category = apps.get_model("categories", "Category")
    GeoPlace = apps.get_model("geometries", "GeoPlace")

    map_root = Category.objects.filter(parent=None, slug="map").first()
    if map_root is None:
        return  # tree not seeded here (0067 never ran on this DB)

    # 1. The transport super-root — promote a stray child of ``map`` if
    #    one exists (staging carried an empty one), else create it.
    super_root = Category.objects.filter(parent=map_root, slug="transport").first()
    if super_root is None:
        super_root = Category.objects.create(
            parent=map_root,
            slug="transport",
            identifier="map.transport",
            name="Transport",
            is_protected=True,
            order=0,
        )
    else:
        super_root.is_protected = True
        super_root.identifier = "map.transport"
        super_root.save(update_fields=["is_protected", "identifier"])

    # 2. Re-parent the transport contract group (child of ``amenity``
    #    since 0067) under its own super-root.
    group = Category.objects.filter(
        slug="transport", parent__slug="amenity", parent__parent=map_root
    ).first()
    if group is None:
        group = Category.objects.filter(
            slug="transport", parent=super_root
        ).first()  # already moved (re-run / partial state)
    if group is not None and group.parent_id != super_root.pk:
        group.parent = super_root
        group.identifier = _identifier(super_root, group.slug)
        group.save(update_fields=["parent", "identifier"])
    if group is None:
        return  # no transport group on this DB — nothing to move/rename

    # 3. Rename the route-mode kinds to Transitland basic route type
    #    names (in place — pk-stable, every FK survives). Guarded
    #    against both-slugs-exist merges: skip and leave for manual
    #    curation (0024 doctrine).
    for old_slug, new_slug in KIND_RENAMES.items():
        child = Category.objects.filter(parent=group, slug=old_slug).first()
        if child is None:
            continue
        if (
            Category.objects.filter(parent=group, slug=new_slug)
            .exclude(pk=child.pk)
            .exists()
        ):
            continue
        _rename(child, new_slug)

    # 4. Stored domains of places anchored on the transport group/kinds
    #    flip to the new super-root slug (derived column, see docstring).
    kind_ids = [group.pk]
    kind_ids += list(Category.objects.filter(parent=group).values_list("pk", flat=True))
    GeoPlace.objects.filter(kind_id__in=kind_ids, domain="amenity").update(
        domain="transport"
    )


def unseed_transport_domain(apps: Any, _schema_editor: Any) -> None:
    """Best-effort reverse: renames and re-parent go back."""
    Category = apps.get_model("categories", "Category")

    map_root = Category.objects.filter(parent=None, slug="map").first()
    amenity = (
        Category.objects.filter(parent=map_root, slug="amenity").first()
        if map_root is not None
        else None
    )
    if amenity is None:
        return  # nothing to re-attach to — leave as-is

    super_root = Category.objects.filter(parent=map_root, slug="transport").first()
    if super_root is None:
        return

    group = Category.objects.filter(slug="transport", parent=super_root).first()
    if group is None:
        return

    for old_slug, new_slug in KIND_RENAMES.items():
        child = Category.objects.filter(parent=group, slug=new_slug).first()
        if child is None:
            continue
        if (
            Category.objects.filter(parent=group, slug=old_slug)
            .exclude(pk=child.pk)
            .exists()
        ):
            continue
        _rename(child, old_slug)

    group.parent = amenity
    group.identifier = _identifier(amenity, group.slug)
    group.save(update_fields=["parent", "identifier"])
    # super-root stays (protected vocabulary row, harmless)


class Migration(migrations.Migration):
    dependencies = [
        ("categories", "0024_rename_resta_category"),
        ("geometries", "0074_reanchor_kind_mode_standard"),
    ]

    operations = [migrations.RunPython(seed_transport_domain, unseed_transport_domain)]

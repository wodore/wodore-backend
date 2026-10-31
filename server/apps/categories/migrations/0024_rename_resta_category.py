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


def _identifier(parent: Any, slug: str) -> str:
    """The computed ``Category.identifier`` expression, inlined.

    ``identifier`` is a stored computed field (computedfields): its
    post_save handlers are registered on the REAL model class and do
    NOT fire for the historical state proxy a migration receives —
    writes that move ``slug``/``parent`` must update ``identifier``
    explicitly (same doctrine as 0006_populate_identifier_field).
    """
    return f"{parent.slug}.{slug}" if parent is not None else f"root.{slug}"


def _rename(category: Any, slug: str) -> None:
    """Slug rename carrying the computed identifier along."""
    category.slug = slug
    category.identifier = _identifier(category.parent, slug)
    category.save(update_fields=["slug", "identifier"])


def _category_foreign_keys(cursor: Any) -> list[tuple[str, str]]:
    """(table, column) of every single-column FK into categories_category.

    Derived from pg_catalog — never hand-enumerated. The staging
    incident round 3: availability's hut_type FKs (HutAvailability,
    HutAvailabilityHistory — and GeoPlace's equivalents) were absent
    from both the original audit and the review's RESTRICT table;
    hand-listing is structurally lossy. Identifiers come from the
    system catalog and are composed via psycopg ``sql`` — never
    interpolated strings.
    """

    cursor.execute(
        """
        SELECT conrelid::regclass::text AS table_name, a.attname AS column_name
        FROM pg_constraint c
        JOIN LATERAL unnest(c.conkey) AS k(attnum) ON true
        JOIN pg_attribute a
          ON a.attrelid = c.conrelid AND a.attnum = k.attnum
        WHERE c.contype = 'f'
          AND c.confrelid = 'categories_category'::regclass
          AND cardinality(c.conkey) = 1
        """
    )
    return [(row[0], row[1]) for row in cursor.fetchall()]


def _repoint_fk(cursor: Any, table: str, column: str, from_pk: int, to_pk: int) -> None:
    """Generic FK re-point — identifiers come from pg_catalog (the
    system's own constraint listing) and are composed via psycopg's
    sql module; only the pks ride as parameters."""
    from psycopg import sql

    query = sql.SQL("UPDATE {} SET {} = %s WHERE {} = %s").format(
        sql.Identifier(*table.split(".")),
        sql.Identifier(column),
        sql.Identifier(column),
    )
    # safe composition: table/column are pg_catalog-derived identifiers
    # quoted via sql.Identifier; only pks ride as parameters
    cursor.execute(query, [to_pk, from_pk])  # nosemgrep


def _category_stragglers(cursor: Any, resta_pk: int) -> list[tuple[str, str, int]]:
    """Rows still referencing resta per FK — the actionable listing
    the guard raises with before the delete."""
    from psycopg import sql

    stragglers: list[tuple[str, str, int]] = []
    for table, column in _category_foreign_keys(cursor):
        query = sql.SQL("SELECT COUNT(*) FROM {} WHERE {} = %s").format(
            sql.Identifier(*table.split(".")), sql.Identifier(column)
        )
        # safe composition: pg_catalog-derived identifiers quoted via
        # sql.Identifier; the pk rides as a parameter
        cursor.execute(query, [resta_pk])  # nosemgrep
        count = cursor.fetchone()[0]
        if count:
            stragglers.append((table, column, count))
    return stragglers


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
        for assoc in GeoPlaceCategory.objects.filter(category=target).order_by()
    }
    reprice_ids: list[int] = []
    drop_ids: list[int] = []
    for assoc in GeoPlaceCategory.objects.filter(category=resta).order_by():
        key = (assoc.geo_place_id, assoc.classifier_id)
        (drop_ids if key in target_pairs else reprice_ids).append(assoc.pk)
    GeoPlaceCategory.objects.filter(pk__in=drop_ids).order_by().delete()
    GeoPlaceCategory.objects.filter(pk__in=reprice_ids).order_by().update(
        category=target
    )

    GeoPlace.objects.filter(kind=resta).order_by().update(kind=target)
    Hut.objects.filter(hut_type_open=resta).order_by().update(hut_type_open=target)
    Hut.objects.filter(hut_type_closed=resta).order_by().update(hut_type_closed=target)

    # Extra schemas: OneToOne per category — the target's own row
    # wins, a legacy row under resta is dropped rather than moved.
    if CategoryExtraSchema.objects.filter(category=target).exists():
        CategoryExtraSchema.objects.filter(category=resta).order_by().delete()
    else:
        CategoryExtraSchema.objects.filter(category=resta).order_by().update(
            category=target
        )

    # Map layer links: unique (layer, category, use) — same dedupe.
    target_uses = {
        (link.layer_id, link.use)
        for link in MapLayerCategory.objects.filter(category=target).order_by()
    }
    keep_links: list[int] = []
    drop_links: list[int] = []
    for link in MapLayerCategory.objects.filter(category=resta).order_by():
        (drop_links if (link.layer_id, link.use) in target_uses else keep_links).append(
            link.pk
        )
    MapLayerCategory.objects.filter(pk__in=drop_links).order_by().delete()
    MapLayerCategory.objects.filter(pk__in=keep_links).order_by().update(
        category=target
    )

    # Children: re-parent to the target. A slug collision means a
    # parallel child exists — fail loudly (deleting resta would
    # CASCADE-delete the child instead of merging it).
    for child in Category.objects.filter(parent=resta).order_by():
        if Category.objects.filter(parent=target, slug=child.slug).exists():
            msg = (
                f"Cannot merge resta#{resta.pk} into restaurant#{target.pk}: "
                f"child slug collision on '{child.slug}' — merge manually."
            )
            raise RuntimeError(msg)
        child.parent_id = target.pk
        # identifier rides along (computed handlers don't fire here)
        child.identifier = _identifier(target, child.slug)
        child.save(update_fields=["parent", "identifier"])

    Category.objects.filter(default=resta).order_by().update(default=target)
    Feature.objects.filter(category=resta).order_by().update(category=target)
    MapLegendSection.objects.filter(category=resta).order_by().update(category=target)
    License.objects.filter(category=resta).order_by().update(category=target)

    # --- catalog-driven sweep + guard (staging round 3) ---------------
    # Re-point EVERY remaining single-column FK into categories_category,
    # then assert zero stragglers with a listing — loud and actionable
    # before the database error. geometries_geoplace_category.category_id
    # is excluded (dedupe-managed above — the (place, category, mode)
    # unique constraint); a multi-column FK would fail at the raw DELETE
    # below, the DB stays the final net.
    from django.db import connection

    with connection.cursor() as cursor:
        for table, column in _category_foreign_keys(cursor):
            if (
                table.endswith("geometries_geoplace_category")
                and column == "category_id"
            ):
                continue
            _repoint_fk(cursor, table, column, resta.pk, target.pk)
        stragglers = _category_stragglers(cursor, resta.pk)
        if stragglers:
            detail = ", ".join(
                f"{table}.{column}: {count} row(s)"
                for table, column, count in stragglers
            )
            msg = (
                f"resta#{resta.pk} still referenced after the merge sweep "
                f"({detail}) — merge these manually"
            )
            raise RuntimeError(msg)

        # Raw SQL delete: the ORM collector's RESTRICT existence checks
        # evaluate related querysets WITH default Meta.ordering — the
        # expression orderings (Lower("name_i18n")) resolve only on real
        # modeltrans classes, never on state proxies (same doctrine as
        # the 0073/0074 backfills). Every reference is re-pointed and
        # asserted clean by now; the DB constraint remains the final net.
        cursor.execute("DELETE FROM categories_category WHERE id = %s", [resta.pk])


def rename_resta_to_restaurant(apps: Any, _schema_editor: Any) -> None:
    Category = apps.get_model("categories", "Category")
    Symbol = apps.get_model("symbols", "Symbol")

    for resta in list(Category.objects.filter(slug="resta").order_by()):
        target = (
            # order_by(): .first() falls back to pk — proxy-safe and
            # deterministic (FK/expressive Meta.ordering must not leak
            # into state-registry queries)
            Category.objects.filter(slug="restaurant", parent_id=resta.parent_id)
            .exclude(pk=resta.pk)
            .order_by()
            .first()
        )
        if target is None:
            # no sibling restaurant: the historical plain rename
            # (identifier updated explicitly — computed-field handlers
            # don't fire on the historical proxy, Claude review PR #473)
            _rename(resta, "restaurant")
        else:
            # both exist: merge (staging shape) — a plain rename would
            # violate unique_slug_per_parent
            _merge_resta_into_restaurant(resta, target, apps)

    # The linked resta symbols are retired (is_active=False) so the
    # stale slug stops being served; category_sync_assets relinks the
    # surviving category to the existing restaurant symbols
    # (slug+style reuse) — independent of the merge above.
    Symbol.objects.filter(slug="resta").order_by().update(is_active=False)


def rename_restaurant_to_resta(apps: Any, _schema_editor: Any) -> None:
    Category = apps.get_model("categories", "Category")
    Symbol = apps.get_model("symbols", "Symbol")
    # Best-effort reverse of the plain rename only: rename the
    # accommodation restaurant back when no resta sibling exists. A
    # merged resta row is gone — merged references stay on
    # restaurant (forward-only, see module docstring).
    for restaurant in Category.objects.filter(
        slug="restaurant", parent__slug="accommodation"
    ).order_by():
        if not Category.objects.filter(
            slug="resta", parent_id=restaurant.parent_id
        ).exists():
            _rename(restaurant, "resta")
    Symbol.objects.filter(slug="resta").order_by().update(is_active=True)


class Migration(migrations.Migration):
    dependencies = [
        ("categories", "0023_category_is_protected"),
    ]

    operations = [
        migrations.RunPython(rename_resta_to_restaurant, rename_restaurant_to_resta),
    ]

"""Re-anchor GeoPlace.kind — mode.standard defines the kind.

The 0073 backfill stored ``kind = first association by (order,
slug)`` alone. The D4 wodore fallback attaches
``accommodation.unknown`` (order 0) with classifier ``mode.reduced``
whenever a hut has reduced-season facts without a known closed type
— order 0 outranks every real open type (camping 25 … alp 55), so
places with both a real open type and the fallback anchored
"unknown". On staging that hit 1285 of 5944 wodore places; worse,
``accommodation.unknown`` carries legacy pk 0 (HutType ids preserved
by categories/0002), which is falsy — ``anchor_kinds_for`` skipped
them and the API served no ``kind`` member at all.

The anchor rule is classifier-aware now (kinds.ANCHOR_CLASSIFIER_
PRIORITY): associations classified ``mode.standard`` outrank every
other association; ties fall through to ``(order, slug)`` as before.
This migration re-runs the derivation for every place that HAS a
mode.standard association — the only rows whose anchor can change.
``domain`` needs no recompute: all affected associations live under
one contract group (accommodation → amenity), so the super-root
stays the same.

Reverse restores the order-only rule on the same subset.
"""

from typing import Any

from django.db import migrations

#: CASE rank mirrors kinds.ANCHOR_CLASSIFIER_PRIORITY — migrations
#: are frozen history, the dict is deliberately not imported.
REANCHOR_SQL = """
    UPDATE geometries_geoplace gp
    SET kind_id = (
        SELECT gpc.category_id
        FROM geometries_geoplace_category gpc
        JOIN categories_category cat ON gpc.category_id = cat.id
        LEFT JOIN categories_category clf ON gpc.classifier_id = clf.id
        WHERE gpc.geo_place_id = gp.id
        ORDER BY
            CASE WHEN clf.identifier = 'mode.standard' THEN 0 ELSE 1 END,
            cat."order",
            cat.slug
        LIMIT 1
    )
    WHERE EXISTS (
        SELECT 1
        FROM geometries_geoplace_category gpcs
        JOIN categories_category clfs ON gpcs.classifier_id = clfs.id
        WHERE gpcs.geo_place_id = gp.id
          AND clfs.identifier = 'mode.standard'
    )
"""

#: Places whose anchor the classifier rule can change — the only
#: rows the forward and reverse SQL touch (documented shape of both
#: statements; inlined per statement below rather than interpolated,
#: migrations use plain literals only).
STANDARD_PLACES_WHERE = """
    WHERE EXISTS (
        SELECT 1
        FROM geometries_geoplace_category gpcs
        JOIN categories_category clfs ON gpcs.classifier_id = clfs.id
        WHERE gpcs.geo_place_id = gp.id
          AND clfs.identifier = 'mode.standard'
    )
"""

REVERSE_SQL = """
    UPDATE geometries_geoplace gp
    SET kind_id = (
        SELECT gpc.category_id
        FROM geometries_geoplace_category gpc
        JOIN categories_category cat ON gpc.category_id = cat.id
        WHERE gpc.geo_place_id = gp.id
        ORDER BY cat."order", cat.slug
        LIMIT 1
    )
    WHERE EXISTS (
        SELECT 1
        FROM geometries_geoplace_category gpcs
        JOIN categories_category clfs ON gpcs.classifier_id = clfs.id
        WHERE gpcs.geo_place_id = gp.id
          AND clfs.identifier = 'mode.standard'
    )
"""


def reanchor(_apps: Any, schema_editor: Any) -> None:
    with schema_editor.connection.cursor() as cursor:
        # same lifted timeout as the 0073 backfill — correlated
        # subquery over the association table
        cursor.execute("SET LOCAL statement_timeout = '120s'")
        cursor.execute(REANCHOR_SQL)


def restore(_apps: Any, schema_editor: Any) -> None:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SET LOCAL statement_timeout = '120s'")
        cursor.execute(REVERSE_SQL)


class Migration(migrations.Migration):
    dependencies = [
        ("geometries", "0073_geoplace_kind_fk"),
    ]

    operations = [
        migrations.RunPython(reanchor, restore),
    ]

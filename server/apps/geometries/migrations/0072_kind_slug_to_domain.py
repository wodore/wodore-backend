"""kind_slug → domain: plain super-root values (vocabulary fix).

The PO vocabulary fix (read-performance follow-up): the super-root
tier member is the place's **domain** — plain ``amenity`` / ``admin``
/ ``natural`` / ``none`` — not a "kind slug" (the kind is the main
category, served as the ``kind`` ref member). Plain values equal the
legacy ``detail_type`` enum, making the API downgrade a pure key
rename. Nothing shipped in a release (the rename rides the same
unreleased API version as the original detail_type → kind_slug
change).

* RenameField ``kind_slug`` → ``domain``; stored values lose the
  ``map.`` prefix (the mass UPDATE lifts the per-row trigger overhead
  past the connection statement timeout — SET LOCAL, see 0066).
* The Meta index moves to the new name; the tiles view is recreated
  (live model import — correct at this point in the chain) and the
  tile function re-created from 0028's frozen template with the
  ``domain`` swaps (see 0068).
"""

import importlib.util
from pathlib import Path
from typing import Any

from django.db import migrations, models


def strip_map_prefix(_apps: Any, schema_editor: Any) -> None:
    with schema_editor.connection.cursor() as cursor:
        # 0066 lesson: per-row pgtrigger overhead on the mass UPDATE —
        # lift the connection statement timeout for this transaction
        cursor.execute("SET LOCAL statement_timeout = '120s'")
        cursor.execute(
            "UPDATE geometries_geoplace "
            "SET domain = substring(domain from 5) "
            "WHERE domain LIKE 'map.%'"
        )


def restore_map_prefix(_apps: Any, schema_editor: Any) -> None:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "UPDATE geometries_geoplace "
            "SET domain = 'map.' || domain "
            "WHERE domain IN ('amenity', 'admin', 'natural')"
        )


def recreate_tiles_view(_apps: Any, schema_editor: Any) -> None:
    from server.apps.geometries.models.tiles_view import GeoPlacesForTilesView

    sql, params = GeoPlacesForTilesView.ViewMeta.query()
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("DROP VIEW IF EXISTS geoplaces_for_tiles CASCADE")
        cursor.execute(f"CREATE VIEW geoplaces_for_tiles AS {sql}", params)


def update_tile_function(_apps: Any, schema_editor: Any) -> None:
    spec = importlib.util.spec_from_file_location(
        "m0028_tile_function",
        Path(__file__).with_name("0028_create_geoplaces_tile_function.py"),
    )
    assert spec is not None and spec.loader is not None
    m0028 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m0028)

    sql = m0028.create_geoplaces_tile_function(forwards_sql=None)
    sql = (
        sql.replace("gp.detail_type,", "gp.domain,")
        .replace("'detail_type' = ANY(fields_array)", "'domain' = ANY(fields_array)")
        .replace("THEN fp.detail_type", "THEN fp.domain")
        .replace("END as detail_type,", "END as domain,")
        .replace('"detail_type": "String"', '"domain": "String"')
        .replace(
            "Available fields: slug, name, importance, kind_slug, elevation,",
            "Available fields: slug, name, importance, domain, elevation,",
        )
        .replace(
            "Available fields: slug, name, importance, detail_type, elevation,",
            "Available fields: slug, name, importance, domain, elevation,",
        )
    )
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(sql)


def remove_tile_function(_apps: Any, schema_editor: Any) -> None:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "DROP FUNCTION IF EXISTS "
            "get_geoplaces_for_tiles(integer, integer, integer, jsonb) CASCADE"
        )


class Migration(migrations.Migration):
    dependencies = [
        ("geometries", "0071_translated_prefix_indexes"),
    ]

    operations = [
        migrations.RenameField(
            model_name="geoplace",
            old_name="kind_slug",
            new_name="domain",
        ),
        migrations.RunPython(strip_map_prefix, restore_map_prefix),
        migrations.RemoveIndex(
            model_name="geoplace",
            name="geometries__kind_sl_c6f402_idx",
        ),
        migrations.AddIndex(
            model_name="geoplace",
            index=models.Index(fields=["domain"], name="geoplace_domain_idx"),
        ),
        migrations.RunPython(recreate_tiles_view, recreate_tiles_view),
        migrations.RunPython(update_tile_function, remove_tile_function),
    ]

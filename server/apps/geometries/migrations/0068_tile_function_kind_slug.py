"""Update the geoplaces tile function for the kind_slug rename.

OpenSpec ``geoplace-category-tree`` (task 3.1): the
``get_geoplaces_for_tiles`` SQL function (created by 0028, embedded
SQL) reads ``detail_type`` from the ``geoplaces_for_tiles`` view —
renamed to ``kind_slug`` by 0066. This migration re-creates the
function from 0028's frozen template with the column renames applied
(importlib from the sibling migration file — migrations never move).

Swaps: the ``gp.detail_type`` projection in the ``filtered_places``
CTE, the sparse-fields gate ``'detail_type' = ANY(fields_array)`` →
``'kind_slug'`` (clients request the field by its new name), the
``fp.detail_type`` projection, and the schema doc entry.
"""

import importlib.util
from pathlib import Path
from typing import Any

from django.db import migrations


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
        sql.replace("gp.detail_type,", "gp.kind_slug,")
        .replace(
            "'detail_type' = ANY(fields_array)",
            "'kind_slug' = ANY(fields_array)",
        )
        .replace("THEN fp.detail_type", "THEN fp.kind_slug")
        .replace("END as detail_type,", "END as kind_slug,")
        .replace('"detail_type": "String"', '"kind_slug": "String"')
        .replace(
            "Available fields: slug, name, importance, detail_type, elevation,",
            "Available fields: slug, name, importance, kind_slug, elevation,",
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
        ("geometries", "0067_category_tree_super_roots"),
    ]

    operations = [
        migrations.RunPython(update_tile_function, remove_tile_function),
    ]

"""Tile asset versions: registry dep coverage + query-aware injection.

Restores the dep-coverage guard lost with the legacy basemaps tests
(commit 3bfc0f2e17 deleted ``server/apps/basemaps/tests.py`` — 106
tests invisible to pytest) and extends it to the geoplaces tile
function registered in ``VERSIONED_TILE_SOURCES``. Plus the
query-aware ``?v=``/``&v=`` injection contract:

* registered sources whose tile URLs carry their own query string
  (geoplaces: ``?category_tree=…``) still get the version appended;
* unregistered query URLs (availability's ``?date={{date}}``) and
  per-request ``{{token}}`` URLs are never touched.
"""

from __future__ import annotations

import re
from importlib import import_module
from typing import Any

from django.apps import apps
from django.test import SimpleTestCase, TestCase

from server.apps.basemaps.seed_lib import ACCOMMODATIONS_STYLE
from server.apps.basemaps.tile_assets import (
    VERSIONED_TILE_SOURCES,
    asset_versions,
    consumed_versions,
    inject_asset_versions,
)
from server.apps.huts.models.tiles_view import HutsForTilesView

#: ``FROM``/``JOIN`` table references in authored SQL.
_TABLE_REF = re.compile(r"(?:FROM|JOIN)\s+([a-z_][a-z0-9_]*)")

#: CTE bindings — ``<name> AS [MATERIALIZED] (`` — resolved in-query,
#: never a physical table.
_CTE_DEF = re.compile(r"([a-z_][a-z0-9_]*)\s+AS\s+(?:MATERIALIZED\s+)?\(")


def _joined_tables(sql: str) -> set[str]:
    """Physical tables an authored SQL string reads from.

    ``FROM``/``JOIN`` targets minus CTE names defined in the same
    string (the geoplaces function's CTE ladder — ``sampled_pois``,
    ``primary_cat``, ``places``, … — would otherwise show up as
    uncovered "tables").
    """
    ctes = set(_CTE_DEF.findall(sql))
    return {table for table in _TABLE_REF.findall(sql) if table not in ctes}


class DepCoverageTests(SimpleTestCase):
    """``deps`` must cover every table the tile view/function joins.

    A future JOIN on an uncovered table (the exact scenario this guard
    exists for — a data edit that does NOT rotate the tile version,
    leaving the CDN on stale tiles) must fail here. No exclusions.
    """

    def test_deps_cover_every_table_joined_by_the_huts_view(self) -> None:
        sql = HutsForTilesView.ViewMeta.query()[0]
        referenced = _joined_tables(sql)
        dep_tables = {
            apps.get_model(label)._meta.db_table
            for label in VERSIONED_TILE_SOURCES["huts"]["deps"]
        }
        assert referenced == dep_tables, (
            f"huts view tables vs deps drift: missing={referenced - dep_tables} "
            f"extra={dep_tables - referenced}"
        )

    def test_deps_cover_every_table_joined_by_the_geoplaces_function(self) -> None:
        migration = import_module(
            "server.apps.geometries.migrations.0076_restore_clustered_geoplaces_tiles"
        )
        sql: str = migration.FUNCTION_SQL
        referenced = _joined_tables(sql)
        # The function's own result cache: a derived table whose rows
        # change on every cache miss — versioning on it would be noise,
        # and a schema change to it cannot make tiles stale.
        referenced -= {"geometries_tile_cache"}
        dep_tables = {
            apps.get_model(label)._meta.db_table
            for label in VERSIONED_TILE_SOURCES["geoplaces"]["deps"]
        }
        assert referenced == dep_tables, (
            f"geoplaces function tables vs deps drift: "
            f"missing={referenced - dep_tables} extra={dep_tables - referenced}"
        )


class RegisteredQueryInjectionTests(SimpleTestCase):
    """Registered sources keep their ``?v=`` through own query params."""

    def test_geoplaces_tile_url_appends_version_after_query(self) -> None:
        versions = {"tiles": {"geoplaces": "deadbeef01234567"}}
        injected = inject_asset_versions(ACCOMMODATIONS_STYLE, versions)
        template: str = injected["sources"]["wd-accommodations"]["tiles"][0]
        assert "&v=deadbeef01234567" in template
        # The function params survive in front of the version
        assert template.index("category_tree=accommodation") < template.index(
            "&v=deadbeef01234567"
        )

    def test_queryless_registered_url_keeps_question_mark_form(self) -> None:
        style = {
            "sources": {
                "s": {
                    "type": "vector",
                    "tiles": ["{{env:MARTIN_TILE_URL}}/huts/{z}/{x}/{y}.mlt"],
                }
            }
        }
        injected = inject_asset_versions(style, {"tiles": {"huts": "abc"}})
        assert injected["sources"]["s"]["tiles"][0].endswith(".mlt?v=abc")

    def test_unregistered_query_url_is_never_touched(self) -> None:
        style = {
            "sources": {
                "s": {
                    "type": "vector",
                    "tiles": [
                        (
                            "{{env:MARTIN_TILE_URL}}/availability/{z}/{x}/{y}.mlt"
                            "?date={{date}}&days=4"
                        )
                    ],
                }
            }
        }
        versions = {"tiles": {"geoplaces": "x", "huts": "y"}}
        injected = inject_asset_versions(style, versions)
        assert injected["sources"]["s"]["tiles"][0] == (
            "{{env:MARTIN_TILE_URL}}/availability/{z}/{x}/{y}.mlt?date={{date}}&days=4"
        )

    def test_registered_url_with_request_token_is_never_touched(self) -> None:
        style = {
            "sources": {
                "s": {
                    "type": "vector",
                    "tiles": [
                        (
                            "{{env:MARTIN_TILE_URL}}/geoplaces/{z}/{x}/{y}.mlt"
                            "?category_tree=accommodation&when={{when}}"
                        )
                    ],
                }
            }
        }
        injected = inject_asset_versions(style, {"tiles": {"geoplaces": "x"}})
        assert injected["sources"]["s"]["tiles"][0] == style["sources"]["s"]["tiles"][0]

    def test_authored_accommodations_style_consumes_geoplaces_version(self) -> None:
        """The ETag/cache-key input rotates with the geoplaces version —
        the authored (tokenized) tree is what ``consumed_versions`` sees
        at serve time."""
        consumed = consumed_versions(
            ACCOMMODATIONS_STYLE, {"tiles": {"geoplaces": "feed"}}
        )
        assert consumed["tiles"]["geoplaces"] == "feed"


class ComputedGeoplacesVersionTests(TestCase):
    """The computed version exists and is aggregate-backed (DB is the
    version source — huts machinery, now keyed on geoplaces deps)."""

    def test_geoplaces_version_present(self) -> None:
        versions = asset_versions(force=True)
        tiles: dict[str, Any] = versions["tiles"]
        assert "geoplaces" in tiles
        assert len(tiles["geoplaces"]) == 16

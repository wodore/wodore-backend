"""The geoplaces near endpoint: cluster members and proximity lookups.

``GET /v1/geoplaces/near`` answers "which places does this map feature
stand for?" for the amenity popups (and any general what's-here click)
— membership data lives in ONE place, shared with the tile function:

* **Cluster mode** (``z`` given): exact server-side-cluster membership
  for the clicked cluster feature. The frontend passes the TILE's zoom
  (not the fractional map zoom), the feature's lngLat (clusters anchor
  on their highest-importance member), the overlay's
  ``category_tree``/``cluster_*`` params from the tiles URL, and — for
  exact per-cluster counts when one grid cell holds several categories
  — the feature's ``category_identifier`` prop. The endpoint snaps the
  anchor to the same grid cell ``get_geoplaces_for_tiles`` groups by
  and returns that cell's clustered members (hybrid band included:
  only ``importance < importance_threshold`` places still cluster
  there — high-importance ones graduated to raw features).
* **Proximity mode** (no ``z``): nearest visible places within
  ``radius`` meters around the point — the what's-here click handler,
  independent of overlays.

Both modes query :sql:`geoplaces_cluster_membership` — the same shared
SQL core the tile function's clustered path aggregates (migration
``geometries.0077``); cluster member lists and tile cluster counts
cannot drift apart. The invariant is pinned by
``tests/apps/geometries/test_geoplaces_near.py`` (every cluster
feature's ``count`` equals the endpoint's ``count`` for its anchor).

Visibility mirrors the tiles: public, active, categorised places only
(no authentication — the same data any anonymous tile request sees).
"""

from __future__ import annotations

import json
import math
from typing import Any, Literal, LiteralString

import psycopg.sql
import pydantic
from dmr import Query, modify
from dmr.routing import path
from pydantic import Field

from django.db import connection

from server.apps.api.controller import ApiController, cache_headers
from server.apps.translations.schema import LanguageQuery

#: Server-side radius cap (meters). Cluster-membership radii derive
#: from the tile grid — the largest grid the overlays use is ~40 km
#: (5000 m at reference zoom 8, doubled per zoom below); 50 km bounds
#: absurd values while never touching legitimate lookups.
RADIUS_MAX_M: float = 50_000.0

#: Field allowlist — the tiles' ``fields`` semantics (comma-separated
#: exact tokens, unknown tokens ignored, absent key = not requested).
#: Defaults are exactly what the popup rows render.
DEFAULT_FIELDS: frozenset[str] = frozenset(
    (
        "slug",
        "name",
        "importance",
        "category_identifier",
        "color",
        "parent_color",
        "elevation",
    )
)
ALLOWED_FIELDS: frozenset[str] = DEFAULT_FIELDS | {"distance"}

#: Tile-parity cluster knobs forwarded into the shared membership
#: helper (the values the overlay's tiles URL carries).
_CLUSTER_PASSTHROUGH: tuple[str, ...] = (
    "cluster_max_zoom",
    "cluster_low_zoom_offset",
    "cluster_radius_m",
    "cluster_ref_zoom",
    "importance_threshold",
)

#: ``order`` values → SQL ORDER BY fragments (id tiebreak keeps pages
#: stable). Single-key ordering only; per-mode defaults resolve in the
#: controller (importance DESC in cluster mode, distance ASC in
#: proximity mode). LiteralString-typed: psycopg.sql.SQL only accepts
#: literals — these fixed fragments are the injection guard.
_ORDER_SQL: dict[str, LiteralString] = {
    "importance": "m.importance DESC, m.id",
    "distance": "distance_m, m.id",
    "name": "resolved_name, m.importance DESC, m.id",
}


class GeoPlacesNearQuery(LanguageQuery):
    """Query parameters for the geoplaces near endpoint."""

    lat: float = Field(
        description="Latitude of the clicked feature/point",
        ge=-90,
        le=90,
        json_schema_extra={"example": 46.0342},
    )
    lon: float = Field(
        description="Longitude of the clicked feature/point",
        ge=-180,
        le=180,
        json_schema_extra={"example": 7.6488},
    )
    z: int | None = Field(
        None,
        ge=0,
        le=24,
        description=(
            "CLUSTER MODE: the TILE zoom the clicked feature comes from "
            "(integer, not the fractional map zoom). Snap to the tile "
            "function's grid at that zoom and return the anchor cell's "
            "clustered members. Present z wins over radius."
        ),
    )
    radius: float | None = Field(
        None,
        gt=0,
        description=(
            "PROXIMITY MODE (when z is absent): search radius in meters, "
            f"silently capped at {RADIUS_MAX_M:.0f}. Ignored when z is given."
        ),
        json_schema_extra={"example": 50},
    )
    category_tree: str | None = Field(
        None,
        description=(
            "Category subtree slug(s), comma-separated — the SAME value "
            "the tiles URL carries in category_tree= (own/parent/"
            "grandparent ancestor match)"
        ),
        json_schema_extra={"example": "accommodation"},
    )
    category_identifier: str | None = Field(
        None,
        description=(
            "Exact primary-category identifier of the clicked cluster "
            "feature (its category_identifier tile property) — pins the "
            "member list to that one cluster when a grid cell holds "
            "several categories"
        ),
        json_schema_extra={"example": "accommodation.hut"},
    )
    cell_x: int | None = Field(
        None,
        description=(
            "EXACT cluster pin: the clicked feature's cell_x tile "
            "property. MVT quantization of the anchor (~±10 m at z9) "
            "can cross a 50 m floor-cell boundary, so anchor snapping "
            "alone cannot reproduce singleton membership at the hybrid "
            "floor — passing the emitted cell ids makes the member set "
            "exact by construction. Falls back to anchor snapping when "
            "absent."
        ),
    )
    cell_y: int | None = Field(
        None,
        description="EXACT cluster pin: the clicked feature's cell_y "
        "tile property (see cell_x).",
    )
    fields: str | None = Field(
        None,
        description=(
            "Comma-separated property allowlist (tiles' fields "
            "semantics; unknown tokens ignored). Default: "
            + ",".join(sorted(DEFAULT_FIELDS))
            + ". Opt-in extra: distance (meters from lat/lon)."
        ),
    )
    order: Literal["importance", "distance", "name"] | None = Field(
        None,
        description=(
            "Result ordering, single key: importance (desc — cluster "
            "mode default), distance (asc — proximity mode default), "
            "name (asc, language-resolved)"
        ),
    )
    limit: int = Field(10, ge=1, le=25, description="Maximum results")
    offset: int = Field(0, ge=0, description="Skip for a light show-more pager")
    cluster_max_zoom: int | None = Field(
        None,
        description="Tile-parity cluster knob (see the tiles URL); default 6",
    )
    cluster_low_zoom_offset: int | None = Field(
        None,
        description="Tile-parity cluster knob; default 2",
    )
    cluster_radius_m: float | None = Field(
        None,
        description="Tile-parity cluster knob; default 5000",
    )
    cluster_ref_zoom: int | None = Field(
        None,
        description="Tile-parity cluster knob; default 8",
    )
    importance_threshold: int | None = Field(
        None,
        description="Tile-parity cluster knob (hybrid-band graduation); default 50",
    )


class NearMemberSchema(pydantic.BaseModel):
    """One place row — every member is fields-gated (absent = not
    requested, never null-padded)."""

    model_config = pydantic.ConfigDict(extra="ignore")

    slug: str | None = None
    name: str | None = None
    importance: int | None = None
    category_identifier: str | None = None
    color: str | None = None
    parent_color: str | None = None
    elevation: int | None = None
    distance: float | None = None


class NearResponseSchema(pydantic.BaseModel):
    """``data`` rows plus ``count`` — total matches BEFORE limit, so a
    client knows whether ``show more`` (offset) has anything left."""

    data: list[NearMemberSchema]
    count: int


# The shared membership core. SYNC: geoplaces_cluster_membership
# (migration geometries.0077) is the single source of truth for grid
# size, cell snapping, the hybrid importance split and the
# visibility/category filters — the tile function aggregates the same
# rows. Change membership logic in the helper, never here.
#
# bounds prefilter: a generous box around the anchor (the cell spans
# at most ~1.5 grid cells per axis; +25% and a kilometer of slack) —
# exactness comes from the cell snap / ST_DWithin, never the box.
_CLUSTER_SQL = """
WITH membership AS (
  SELECT
    m.*,
    COUNT(*) OVER () AS total_count,
    ST_Distance(
      ST_Transform(m.location_3857, 4326)::geography,
      ST_GeomFromText(%(anchor)s, 4326)::geography
    ) AS distance_m
  FROM geoplaces_cluster_membership(
    %(z)s,
    ST_Transform(
      ST_Expand(
        ST_Transform(ST_GeomFromText(%(anchor)s, 4326), 3857),
        %(margin)s
      ),
      4326
    ),
    %(params)s::jsonb
  ) m
  WHERE m.is_clustered
    AND m.cell_x = COALESCE(%(cell_x)s::int, ROUND(ST_X(ST_Transform(ST_GeomFromText(%(anchor)s, 4326), 3857)) / NULLIF(m.grid_size, 0)))
    AND m.cell_y = COALESCE(%(cell_y)s::int, ROUND(ST_Y(ST_Transform(ST_GeomFromText(%(anchor)s, 4326), 3857)) / NULLIF(m.grid_size, 0)))
    AND (%(category_identifier)s::text IS NULL OR m.category_identifier = %(category_identifier)s)
  ORDER BY {}
  LIMIT %(limit)s OFFSET %(offset)s
)
SELECT slug, resolved_name, importance, elevation, category_identifier,
       color, parent_color, distance_m, total_count
FROM membership
"""

# Proximity mode: same shared visibility/filters via the helper (z
# pinned to 0 — the grid outputs are unused, only the >=50 m floor
# matters, keeping the cell snap division well-defined), exact
# distance via geography ST_DWithin. NEVER applies the importance
# split or grid logic — a what's-here click must see every public
# place in radius, whatever its cluster class would be (pinned by
# test: the graduated high-importance viewpoint is returned).
_PROXIMITY_SQL = """
WITH membership AS (
  SELECT
    m.*,
    COUNT(*) OVER () AS total_count,
    ST_Distance(
      ST_Transform(m.location_3857, 4326)::geography,
      ST_GeomFromText(%(anchor)s, 4326)::geography
    ) AS distance_m
  FROM geoplaces_cluster_membership(
    0,
    ST_Transform(
      ST_Expand(
        ST_Transform(ST_GeomFromText(%(anchor)s, 4326), 3857),
        %(margin)s
      ),
      4326
    ),
    %(params)s::jsonb
  ) m
  WHERE ST_DWithin(
    ST_Transform(m.location_3857, 4326)::geography,
    ST_GeomFromText(%(anchor)s, 4326)::geography,
    %(radius)s
  )
  ORDER BY {}
  LIMIT %(limit)s OFFSET %(offset)s
)
SELECT slug, resolved_name, importance, elevation, category_identifier,
       color, parent_color, distance_m, total_count
FROM membership
"""


def _helper_params(query: GeoPlacesNearQuery) -> dict[str, Any]:
    """The jsonb the shared membership helper parses (lang + the tile
    parity knobs + the category filters it understands)."""
    params: dict[str, Any] = {"lang": query.lang}
    for key in _CLUSTER_PASSTHROUGH:
        value = getattr(query, key)
        if value is not None:
            params[key] = value
    if query.category_tree:
        params["category_tree"] = query.category_tree
    return params


def _selected_fields(raw: str | None) -> frozenset[str]:
    if raw is None:
        return DEFAULT_FIELDS
    tokens = {token.strip() for token in raw.split(",") if token.strip()}
    return frozenset(tokens & ALLOWED_FIELDS)


class GeoPlacesNearController(ApiController):
    """Cluster members (z) or nearest places (radius) around a point."""

    @modify(
        operation_id="near_geoplaces",
        headers=cache_headers(60),
    )
    def get(self, parsed_query: Query[GeoPlacesNearQuery]) -> NearResponseSchema:
        """Places near a point — cluster membership or proximity.

        Cluster mode (``z`` given) returns the members of the clicked server-side cluster feature — snapped to the tile function's grid cell at that zoom; proximity mode (``z`` absent) returns the nearest places within ``radius`` meters. Response: ``{data: [...], count: <total before limit>}``.
        """
        query = parsed_query
        params = _helper_params(query)
        anchor_wkt = f"POINT({query.lon} {query.lat})"
        order_key = query.order or ("importance" if query.z is not None else "distance")
        # ORDER BY cannot be a bind parameter — compose the statement
        # with psycopg.sql instead of string interpolation: the fragment
        # comes from the fixed _ORDER_SQL table above, keyed by the
        # validated ``order`` literal — no client string ever reaches
        # the SQL text.
        order_by = psycopg.sql.SQL(_ORDER_SQL[order_key])
        cluster_sql = psycopg.sql.SQL(_CLUSTER_SQL).format(order_by)
        proximity_sql = psycopg.sql.SQL(_PROXIMITY_SQL).format(order_by)

        with connection.cursor() as cursor:
            if query.z is not None:
                # Cluster mode: margin from the shared grid formula —
                # the same function the membership helper uses.
                cursor.execute(
                    "SELECT geoplaces_cluster_grid_size(%s, %s::jsonb)",
                    [query.z, _json(params)],
                )
                grid_size = float(cursor.fetchone()[0])
                margin = 1.6 * grid_size + 1000 if grid_size > 0 else 1000
                cursor.execute(
                    cluster_sql,
                    {
                        "anchor": anchor_wkt,
                        "z": query.z,
                        "params": _json(params),
                        "margin": margin,
                        "category_identifier": query.category_identifier,
                        "cell_x": query.cell_x
                        if query.cell_x is not None and query.cell_y is not None
                        else None,
                        "cell_y": query.cell_y
                        if query.cell_x is not None and query.cell_y is not None
                        else None,
                        "limit": query.limit,
                        "offset": query.offset,
                    },
                )
            else:
                radius = min(
                    query.radius if query.radius is not None else 10_000.0,
                    RADIUS_MAX_M,
                )
                cursor.execute(
                    proximity_sql,
                    {
                        "anchor": anchor_wkt,
                        "params": _json(params),
                        # The bbox prefilter is in PROJECTED 3857 units
                        # while the exact ST_DWithin filter below is in
                        # ground meters — radius projected units cover
                        # only radius*cos(lat) ground meters, silently
                        # dropping the ~0.68R–R annulus at 47°N. Scale
                        # the margin by 1/cos(lat) (Opus review S1).
                        "margin": (radius + 1000) / math.cos(math.radians(query.lat)),
                        "radius": radius,
                        "limit": query.limit,
                        "offset": query.offset,
                    },
                )
            columns = [col[0] for col in cursor.description]
            rows = cursor.fetchall()

        selected = _selected_fields(query.fields)
        total = int(rows[0][columns.index("total_count")]) if rows else 0
        members: list[NearMemberSchema] = []
        for row in rows:
            record = dict(zip(columns, row, strict=True))
            member: dict[str, Any] = {}
            if "slug" in selected:
                member["slug"] = record["slug"]
            if "name" in selected:
                member["name"] = record["resolved_name"]
            if "importance" in selected:
                member["importance"] = record["importance"]
            if "category_identifier" in selected:
                member["category_identifier"] = record["category_identifier"]
            if "color" in selected:
                member["color"] = record["color"]
            if "parent_color" in selected:
                member["parent_color"] = record["parent_color"]
            if "elevation" in selected:
                member["elevation"] = record["elevation"]
            if "distance" in selected:
                distance = record["distance_m"]
                member["distance"] = round(float(distance), 1) if distance else 0.0
            members.append(NearMemberSchema(**member))

        return NearResponseSchema(data=members, count=total)


def _json(params: dict[str, Any]) -> str:
    return json.dumps(params)


paths = [
    path(
        "near",
        GeoPlacesNearController.as_view(),
        name="near_geoplaces",
    ),
]

# Design: add-geoplaces-near

## Context

`get_geoplaces_for_tiles` (restored in `geometries.0076`) clusters POIs
at low zooms by `(primary category, grid cell)` with a hybrid
transition band where `importance >= importance_threshold` places
graduate to raw features. Cluster features carry `count` but no
identity; the popup needs the members.

## Goals / Non-goals

Goals: exact cluster membership via the API; shared, drift-proof
membership logic; tile elevation + transition identity; instant-paint
props for individual features.

Non-goals: in-tile members (tile-size evidence above); proximity
search replacing the richer `/v1/geo/places/nearby` (that endpoint
stays untouched — near is the tiles-parity click companion).

## Decisions

### D1 — The shared core is SQL, not Python

The tile function is plpgsql; only a SQL core can be shared with it.
`geoplaces_cluster_membership(z, bounds, params)` returns one row per
visible place with primary category, language-resolved name, elevation,
3857 location, `cell_x`/`cell_y` (`ROUND(coord / grid_size)`, NULL
beyond the clustering band), `grid_size` and `is_clustered` (the hybrid
split `(z <= cluster_max_zoom OR importance < threshold) AND
grid_size >= 50`). The tile function aggregates the rows (clusters =
`is_clustered` grouped by category+cell; the graduated twin = `NOT
is_clustered`); the near endpoint filters one cell. The grid formula
lives in `geoplaces_cluster_grid_size` alone — the tile function's
former inline plpgsql computation is deleted, not duplicated. `SYNC`
comments sit at both call sites and the invariant test is the
tripwire.

The helper is **plpgsql, not `LANGUAGE sql`** — two planner traps
caught in the lane benchmark (440k-row dataset):

- a `LANGUAGE sql` body **inlines** into the caller, turning the
  `bounds` argument expression into a SubPlan that cannot serve as a
  GIST index condition → full-table filter per tile;
- blocking inlining (Function Scan) with the filter arrays as **CTE
  columns cross-joined** into the scan degrades the array conditions
  to per-row correlated SubPlans (441k executions, >30× slower).

plpgsql parameter extraction gives the membership query plain plan
parameters — the exact shape 0076 shipped — with `#variable_conflict use_column`
(cold generations, `cache_ttl_days=0`, shared dev postgres under load):

| tile (tourism tree) | 0076 | 0077 |
| --- | --- | --- |
| z5 whole-Europe clusters | 7.5 s / 19 186 B | 10.8 s / 19 197 B |
| z6 | 7.1 s / 56 405 B | 9.4 s / 56 416 B |
| z8 hybrid band | 0.3 s / 45 103 B | 0.6 s / 54 969 B |
| z11 raw | 0.16 s | 0.28 s |
| z13 raw | 0.14 s | 0.24 s |

≈1.3–1.9× slower cold clustered generations (the Function-Scan
materialization overhead), amortized by the DB tile cache; z8 grows
by design (real twin identity + elevation — the feature). Near
queries: 0.2–1.4 s per click on real data.

### D2 — Path: `/v1/geoplaces/near` (top-level)

The frontend codes the literal path; app prefixes already vary
(`geo/`, `map/`, `categories/`) so a `geoplaces/` router prefix in
`api_v1.py` is consistent routing, not an exception.

### D3 — `category_identifier` pins the exact cluster

Clusters group by `(category_identifier, cell)`: one cell can hold
several category clusters (a hut bubble and a hotel bubble side by
side). `category_tree` alone would mix them, so the endpoint accepts
`category_identifier` — the clicked feature's own tile property — and
the frontend forwards it (a one-line addition to their client module;
reported for reconciliation). The sync invariant test pins counts with
it.

### D4 — Both modes route through the helper

Proximity mode pins `z = 0` (grid outputs unused — only the ≥ 50 m
floor keeps the cell snap division defined), prefilter-boxes via
`bounds`, then exact-filters with `ST_DWithin(...::geography)` on
transformed locations (geography needs 4326; the helper returns 3857).
That shares the visibility/category WHERE verbatim and provably never
applies the importance split or grid logic (pinned by test: the
graduated viewpoint is returned next to low-importance huts).

### D5 — Elevation is an opt-in tile field, identity is unconditional

`elevation` rides the `fields` allowlist (NULL → omitted from MVT when
not requested) so non-opting consumers' tiles stay byte-identical and
fresh tiles for the overlays come free via the params-hash cache-key
rotation. The twin's `slug` is unconditional (identity is not
selectable) and `name` keeps the `max_label_zoom` gate; because that
fix rides no param, the migration purges `geometries_tile_cache`.

### D6 — Envelope, ordering, limits

`{data, count}` (count = total before limit, so "show more" knows
whether to offer it). `fields` uses the tiles' exact-token semantics
(default = the popup set). `order` is a single validated literal with
per-mode defaults (importance desc in cluster mode, distance asc in
proximity). `limit` 1–25 (default 10), `radius` silently capped at
50 km (a 422 on previously-accepted values would be an observable
contract change; a cap on a click-lookup radius is not).

## Risks / Trade-offs

- The helper adds one function-scan layer to the clustered tile path —
  the tile-size/generation benchmark on the lane DB (post-migration,
  representative zooms per tier) guards regressions; the tile cache
  absorbs repeats.
- COUNT(*) OVER () computes totals over all cell members before the
  limit — bounded by cell size at clustered zooms (hundreds at worst).
- `cache_ttl_days` remains a tile-side concern; the near endpoint is
  uncached at the DB level (click-driven, rare) with 60 s CDN headers.

## Migration Plan

One migration (`geometries.0077`): create the two helper functions →
purge the tile cache → rebuild `get_geoplaces_for_tiles`. The endpoint
and styles land in the same deploy; `map_seed` re-serve rotates the
styles' `?v=` (row `modified` rotates → clients refetch → new tile URL
templates → fresh DB cache keys).

## Open Questions

None — the frontend contract is locked (see proposal); the
`category_identifier` addition is reported for reconciliation.

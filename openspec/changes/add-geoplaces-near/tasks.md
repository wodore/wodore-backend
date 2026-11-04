# Tasks: add-geoplaces-near

## 1. Shared membership core (migration geometries.0077)

- [x] 1.1 `geoplaces_cluster_grid_size(z, params)` — the grid formula as a pure SQL function (full-zone scaling, hybrid interpolation toward 50 m, 0 beyond the band)
- [x] 1.2 `geoplaces_cluster_membership(z, bounds, params)` — visibility (public/active/categorised), exact/subtree category filters, primary category, language-resolved name, elevation, 3857 location, cell snap, `is_clustered`
- [x] 1.3 Rebuild `get_geoplaces_for_tiles` clustered path on the helper (cluster aggregation + graduated twin both read the shared rows); delete the inline plpgsql grid computation
- [x] 1.4 SYNC comments at both call sites + `tiles_view.py` contract/changelog update

## 2. Tile field widening + transition identity

- [x] 2.1 `elevation` opt-in field in the tile function (raw path + transition twin; clusters NULL; omitted when not requested)
- [x] 2.2 Transition twin carries real `slug` (unconditional) and language-resolved `name` (max_label_zoom-gated)
- [x] 2.3 Purge `geometries_tile_cache` in the migration (identity fix rides no query param)
- [x] 2.4 All eleven overlay styles (accommodations + ten subtrees, full + subset twins) request `category_identifier,elevation` in their tiles `fields`
- [x] 2.5 Tile-function tests: elevation opt-in/absence/cluster-NULL, twin slug/name, full-zone anonymity

## 3. `GET /v1/geoplaces/near`

- [x] 3.1 Cluster mode: anchor→cell snap via the helper's own grid, members of the pinned category (or all categories), importance-ordered
- [x] 3.2 Proximity mode: ST_DWithin geography radius, distance-ordered, never applies split/grid logic (pinned by test)
- [x] 3.3 Params: lat/lon, z, radius (50 km cap), category_tree, category_identifier, fields (tiles semantics), order (single literal, per-mode defaults), limit (≤25)/offset, lang, cluster knobs passthrough
- [x] 3.4 Envelope `{data, count}` with fields-gated rows (absent ≠ null)
- [x] 3.5 Mount at `/v1/geoplaces/near` (top-level `geoplaces/` router)

## 4. Sync invariant + suite

- [x] 4.1 Invariant test: every tier band shape × probe zooms, every cluster feature's `count` == near(anchor, z, category_identifier).count (MVT geometry decoded to the anchor lngLat)
- [x] 4.2 Endpoint contract tests: modes, ordering, fields, pager, caps, validation
- [x] 4.3 Full suite green; pyrefly clean
- [ ] 4.4 Lane-DB benchmark: clustered tile generation time/size at representative zooms pre/post helper (post-migration; recorded in the work doc)

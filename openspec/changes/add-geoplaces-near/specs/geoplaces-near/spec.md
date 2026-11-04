# geoplaces-near Delta

## ADDED Requirements

### Requirement: Cluster membership sync invariant

The near endpoint's cluster mode SHALL return exactly the members of
the clicked server-side cluster feature: for a tile request with
parameters P at zoom z, every cluster feature in that tile SHALL have
its `count` equal the endpoint's `count` for a query at the feature's
anchor coordinates with `z`, the category filters and the cluster
knobs of P. Both surfaces SHALL read one shared SQL membership core
(`geoplaces_cluster_membership` / `geoplaces_cluster_grid_size`); the
tile function's clustered path SHALL aggregate that core's rows and
the endpoint SHALL filter them — duplicated membership logic that can
drift is out of scope by construction, and a drift-regression test
SHALL pin the invariant across every tier band shape (full-clustering
zooms and the hybrid transition band).

#### Scenario: Cluster count equals near count

- **WHEN** a tile at zoom z (any tier band) contains a cluster feature with `count` N and anchor A
- **THEN** `GET /v1/geoplaces/near?lat/lon=A&z=z` with the same category filters, `category_identifier` and cluster knobs returns `count == N` and its `data` rows are that cluster's members

#### Scenario: Hybrid band membership follows the importance split

- **WHEN** zoom z is in the transition band (`cluster_max_zoom < z <= cluster_max_zoom + offset`)
- **THEN** a cluster's members are exactly the cell's places with `importance < importance_threshold` (graduated places are raw features, never cluster members), matching the tile aggregation

#### Scenario: One cell, several category clusters

- **WHEN** one grid cell holds clusters of different `category_identifier`s
- **THEN** each cluster's members are returned separately — a query carrying the clicked feature's `category_identifier` counts exactly that cluster, never the cell's mixed total

### Requirement: Proximity mode returns every visible place in radius

The near endpoint's proximity mode (no `z`) SHALL return the nearest
visible places within `radius` meters of the point, ordered by
distance — it SHALL NOT apply the cluster importance split, grid
membership or any cluster class: a what's-here click sees every
public, active, categorised place in radius regardless of what the
tile clustering would do with it.

#### Scenario: Graduated place returned in proximity mode

- **WHEN** a place with `importance >= importance_threshold` (graduated raw in the tile hybrid band) sits within the requested radius
- **THEN** proximity mode returns it alongside low-importance neighbours

#### Scenario: Radius is capped, not rejected

- **WHEN** `radius` exceeds 50 km
- **THEN** the request succeeds with the radius clamped to 50 km (no 422 — previously-accepted input shapes stay accepted)

### Requirement: Request contract

The endpoint SHALL accept `lat`/`lon` (required), `z` (int — selects
cluster mode; present `z` wins over `radius`), `radius` (meters,
proximity mode), `category_tree` (comma-separated subtree slugs — the
same semantics and value space the tiles URLs carry), `category_identifier`
(exact primary-category pin), `fields` (comma-separated allowlist with
the tiles' exact-token semantics; default
`slug,name,importance,category_identifier,color,parent_color,elevation`,
opt-in `distance`), `order` (single key: `importance` desc — cluster
default, `distance` asc — proximity default, `name` asc), `limit`
(1–25, default 10), `offset`, `lang` (language-resolved names, both
modes) and the tile-parity cluster knobs (`cluster_max_zoom`,
`cluster_low_zoom_offset`, `cluster_radius_m`, `cluster_ref_zoom`,
`importance_threshold` — identical defaults to the tile function; a
cluster's membership depends on the params of the tile request that
produced it, so clients forward what the style's tiles URL carries).

#### Scenario: Tile-parity knobs are honoured

- **WHEN** an overlay's tiles URL carries `cluster_max_zoom=7&cluster_radius_m=5000` and its cluster popup calls near with the same knobs and the tile's z
- **THEN** the returned membership matches that overlay's tiles exactly (the sync invariant holds per-overlay, not just for defaults)

#### Scenario: Field allowlist gates rows

- **WHEN** `fields=slug,elevation` is requested
- **THEN** each `data` row carries exactly `slug` and `elevation` (absent keys are omitted, never null-padded)

### Requirement: Response envelope

The response SHALL be `{"data": [...], "count": <total matches before
limit>}` so a client knows whether `offset` paging has anything left;
`data` length SHALL be `min(count - offset, limit)` when paging within
results. The endpoint SHALL be public (no authentication) and expose
only places visible to anonymous tile requests.

#### Scenario: Count exceeds the page

- **WHEN** a cluster has 30 members and `limit=10`
- **THEN** `count` is 30 and `data` carries the 10 highest-ordered members

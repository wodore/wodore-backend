# Proposal: add-geoplaces-near

## Why

The amenity overlays (accommodations + ten amenity subtrees) render
server-side cluster bubbles, but a cluster popup needs the members —
which places the bubble stands for, with names, elevation and category
colors for its rows. Baking member lists into the tiles was benchmarked
on staging and rejected: tiles balloon +100–370 % because many clusters
are small (tourism z8: 234 KB → 608 KB, generation time +56 %). Members
are per-click data, not per-tile data.

Two tile gaps ride along because the popup also paints directly from
tile properties when it can: individual features carry no `elevation`
(opt-in field, absent today), and the clustered path's transition-zone
twin — graduated high-importance individuals at
`cluster_max_zoom < z <= max+offset` — emits empty `name`/`slug`,
leaving hybrid-band markers without identity for promoteId, selection
or popup lookups.

## What Changes

- **Shared membership core (SQL)**: `geoplaces_cluster_grid_size` (the
  grid-size formula, one definition) and `geoplaces_cluster_membership`
  (visibility + category filters, primary category, cell snap, hybrid
  importance split) — the tile function's clustered path aggregates
  these rows and the new endpoint queries them, so membership cannot
  drift between tiles and the API. Migration `geometries.0077` swaps
  the tile function onto the helper and purges `geometries_tile_cache`
  (the identity fix rides no query param).
- **`GET /v1/geoplaces/near`** (public, unauthenticated): cluster mode
  (`z` given — the TILE zoom) snaps the anchor to the same grid cell
  the tile function groups by and returns that cell's clustered
  members; proximity mode (`z` absent) returns nearest visible places
  within `radius` meters (capped 50 km). Envelope `{data, count}` with
  tiles-semantics `fields` gating, single-key `order`, `limit`/`offset`
  pager.
- **Tile field widening**: all eleven overlay styles request
  `elevation` + `category_identifier` in their tiles `fields` —
  `elevation` becomes an opt-in tile-function field (NULL when not
  requested: everyone else's tiles stay byte-identical; the fields
  change rotates the DB tile-cache key and the served styles' `&v=`
  automatically). The transition twin carries real `slug`/`name`
  (names still gated by `max_label_zoom`).
- **Invariant test**: for every tier band shape and probe zoom, every
  cluster feature's `count` equals the endpoint's `count` for its
  anchor — the drift tripwire.

## Non-goals

- Member lists inside tiles (rejected on staging tile-size evidence).
- Any change to the frontend repo; the frontend codes against this
  contract (wodore-frontend-quasar #384).
- API version bump — the endpoint and tile fields are additive.

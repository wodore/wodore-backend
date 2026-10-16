# Design — map-layers-api

## Context

Three indexes serve map layer metadata today: `/v1/map/config` (rich; all
variants; 13 small styles inlined; `cache_page(6h)` on LocMem — per worker),
`/v1/map/catalog` (Martin-compatible selector view) and the style endpoint
(version-keyed render cache + ETag, instant). Resolution of device tiers is
client-side (`pickVariant`); the backend walks "exact → nearest → single",
which upgrades `medium` requests to `high` on a tie.

Decisions below were converged with product over the #285/#328 staging
incidents; the guiding rule is **one catalog, backend-owned resolution,
revalidation instead of TTLs**.

## Decision 1 — One catalog: `GET /v1/map/layers`

Replaces `/v1/map/config`. Response is a collection envelope
(`{"layers": [...]}`) — not a bare array (extensibility: count/pagination can
be added additively; consistent with the house envelope rule).

Each entry is **the resolved layer** — no `variants[]`:

```jsonc
{
  "slug": "huts", "role": "overlay", "name": "Huts", "icon": "huts",
  "icon_badge": "", "order": 0, "show": true, "is_default": false,
  "min_zoom": 5, "max_zoom": null, "coverage_bbox": null,
  "spec": "high",                                  // served tier
  "style_url": "/v1/map/styles/huts.json?spec=high",
  "modified": "2026-10-15T22:29:11.528Z",           // was `version`
  "parameters": [...], "categories": [...], "attributions": [...],
  "legend": {...}, "config": {...}, "interaction": {...}, "anchors": {...}
}
```

- `spec` (wanted) is a query param; the backend resolves and answers with the
  **served** `spec` — the client states intent, never policy.
- Spec-scoped fields (parameters, attributions, legend, config, interaction,
  anchors) serialize from the **resolved row**. The data model already scopes
  them per row, and `MapLayer.clean()` enforces per-row token coverage.
- Legend serving becomes per-row by this change; the seed keeps sharing one
  `MapLegend` row across variants (divergence opt-in, not default).
- Sparse fieldsets (`?fields[map_layers]=…`) apply — the basemap picker gets a
  thin view from the same endpoint (existing `SparseFieldsQuery` machinery).

`GET /v1/map/layers/{slug}` returns the same object; ETag per layer.
`GET /v1/map/slots` returns `{"slots": [...]}` (2 rows; leaves the collection).

## Decision 2 — Explicit spec fallback chain (behavior change)

```python
SPEC_FALLBACKS = {
    "low": ("medium", "high"),
    "medium": ("low", "high"),
    "high": ("medium", "low"),
}
```

Exact match → chain walk → single remaining variant → else 404. Cheap-first
for `medium` (today: `high`). One shared implementation used by `layers`,
`layers/{slug}`, `styles/{slug}` and `catalog` (`MapLayer.pick_variant`
rewritten; `SPEC_ORDER` distance-walk removed). Tests pin all three chains
plus the single-variant and no-variant cases.

## Decision 3 — No inline styles

`INLINE_STYLE_MAX_BYTES` and the inline path in `_build_variant` are removed.
Rationale: inline styles ride the whole catalog payload (any unrelated edit
re-downloads all of them), cannot 304 individually, and bypass the per-layer
persisted style cache that already keys on `modified`. Cold boot pays N small
same-host HTTP/2 fetches; warm boots fetch nothing (version compare).

## Decision 4 — Version-keyed ETag caching (replaces `cache_page`)

- **Catalog version**: `sha256` over `name:count:max(modified)` of every model
  the payload serializes — `MapLayer, MapSlot, MapParameter, MapLegend,
  MapLegendSection, MapLegendItem, MapLegendLink, MapLayerCategory,
  MapLayerParameter, MapLayerAttribution, Category, Organization, License`.
  Deletes are caught by the count; edits by `max(modified)`. Uncached per
  request except a ≤10 s memo (staleness bound acceptable: "next reload").
- **ETag input**: version ∪ `lang` ∪ `spec` ∪ `role` ∪ `show` ∪ sorted
  fieldset params ∪ resolved Api-Version (the middleware may transform
  pinned responses; its `Vary` header already matches). Strong ETag, manual
  `If-None-Match` → 304 handling.
- **Body cache**: rendered JSON in the Django cache keyed by the ETag
  (version-keyed ⇒ self-busting; TTL 24 h). LocMem is acceptable (bodies are
  deterministic); per-worker duplication is harmless.
- **Headers** (layers, layers/{slug}, slots, styles, catalog):
  `Cache-Control: public, max-age=0, must-revalidate, stale-if-error=604800`
  — one online reload is guaranteed fresh; offline serves the stored copy;
  a future CDN can share 304s (`public`). Explicitly **not**
  `stale-while-revalidate` (that is the two-reload behavior product rejected).

## Decision 5 — Catalog becomes Martin parity only

`/v1/map/catalog` serves `{"styles": {slug: {name, path}}}` with `?spec=`
resolved into `path`. It is a debug/compat view; no app consumer after the
frontend rewire. `/v1/map/config` is removed. Both fold into the unreleased
API version (snapshot regen + contract tests).

## Migration & compatibility

- All breaking changes ride the still-unreleased API version (amend its
  `VersionChange`; no new version, no stacked release).
- Frontend follow-up (separate repo/PR, listed in tasks as coordination):
  basemaps consume `layers`; delete `fetchBasemapCatalog`, the persisted
  `mapBasemapCatalogCache`, `refreshBasemaps`, `martinCatalogBasemap`,
  `STYLE_VERSION`, client-side `pickVariant`; optional `visibilitychange`
  revalidate for long-lived tabs.
- `map_seed` unchanged (row data drives everything; `show`/`order` already
  seeded).

## Risks / trade-offs

- `modified` bumps on any row save (e.g. `show`-only) → occasional
  unnecessary style revalidation (a 304). Accepted over content hashing.
- Per-request aggregate queries (≤13 small tables, memoized 10 s) replace a
  zero-query page cache — bounded and predictable.
- Losing inline styles adds cold-boot requests for 13 small overlays —
  same-host, multiplexed, cached thereafter.

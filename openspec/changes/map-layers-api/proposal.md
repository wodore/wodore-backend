## Why

After the catalog migration the map API serves three overlapping indexes: `/v1/map/config` (rich, all spec variants, inline small styles, 6 h page-cache), `/v1/map/catalog` (Martin-compatible selector view), and `/v1/map/styles/{slug}.json` (version-keyed, instant). The split produced the failure modes seen on staging: catalog metadata (`show`, order) propagating for hours, basemap style URLs resolving against the wrong origin (frontend #285), duplicated basemap picker entries, and an unowned spec-fallback order (a `medium` request currently upgrades to `high` on a tie). The frontend maintains two parallel fetch/persist/refresh pipelines because neither index is a strict superset of the other.

The device-tier model also forces client-side variant selection (`pickVariant`) even though the client only knows what it *wants* — the backend knows what exists.

## What Changes

- **`GET /v1/map/layers`** replaces `/v1/map/config` as the single catalog for clients:
  - Response is the generic collection envelope `{ "data": [...], "count": N }` (house standard — no per-resource keys, no bare arrays; pagination would be additive if ever needed, none here), no `variants[]` array. The backend resolves the variant server-side from `?spec=` and serves **one resolved layer per slug**: `spec` (what was served, fallback applied) and `style_url` (spec-resolved) instead of all variants.
  - **No inline styles** anywhere (`INLINE_STYLE_MAX_BYTES` is removed) — style documents are served exclusively by the style endpoint, which is already version-keyed and ETagged per layer.
  - Spec-scoped fields come from the **resolved row**: `parameters`, `attributions`, `legend`, `config` (filters), `interaction`, `anchors`. Identity fields (slug, role, name, icon, order, show, is_default, zoom bounds, coverage) are slug-scoped.
  - Query params: `lang`, `spec` (wanted tier), `role`, `show` (opt-in visibility filter — default unfiltered because hidden fallback basemaps must stay resolvable client-side), and **sparse fieldsets** (`?fields[map_layers]=slug,name,…`, existing `SparseFieldsQuery` machinery).
  - Caching: **version-keyed ETag + revalidate-always** (`Cache-Control: public, max-age=0, must-revalidate, stale-if-error=604800`). The ETag input is catalog-version ∪ lang ∪ spec ∪ role ∪ fields ∪ resolved Api-Version. The version is a cheap exact aggregate (`max(modified)` + counts over every model the payload serializes), memoized ≤10 s; rendered bodies are cached in the Django cache keyed by that version (replaces `cache_page`, which is removed). One reload (online) always yields current data.
- **`GET /v1/map/layers/{slug}`**: the same resolved layer object, per-layer ETag (`modified` ∪ spec ∪ lang). Shares the summary builder with the collection.
- **`GET /v1/map/slots`**: `{ "data": [{slug, label, order}], "count": N }` — the slot list leaves the layers payload.
- **`GET /v1/map/catalog`** is slimmed to Martin parity: `{ "styles": { "<slug>": { "name", "path" } } }`, `path` spec-resolved via `?spec=`. No selector metadata — it becomes the Martin-compat/debug view, not an app data source.
- **`GET /v1/map/config` is removed** (folded into the still-unreleased API version together with the catalog slim-down; snapshot regenerated).
- **Spec fallback chain becomes explicit and cheap-first**: `low → medium → high`, `medium → low → high`, `high → medium → low` (today `medium` falls back to `high` first — the exact-match/nearest/single walk upgrades mid-tier devices to the heaviest variant). The chain is pinned by tests.
- **Legend is spec-scoped** in serving: the resolved row's `legend` FK is served. Sharing one `MapLegend` row across variants remains the seed default; per-spec divergence is now first-class (different sources/styles can carry different legends).
- **`modified`** (ISO 8601, `TimeStampedModel`) replaces the `version` field name; it already is the render-cache key and becomes the client style-cache key.
- **Style endpoint caching header fixed**: `Cache-Control` on `/v1/map/styles/*` (and the external-style redirect) becomes revalidate-always + `stale-if-error` — the server cache is already version-keyed; only the browser-side header lagged 6 h.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `map-style-api`: catalog/config endpoints are replaced by `layers` + `layers/{slug}` + `slots`; catalog slimmed to Martin parity; spec resolution chain made explicit; caching model redefined (version-keyed ETag, no time-based page cache); inline styles removed.
- `map-layer-catalog`: the device-tier fallback requirement changes (explicit chain, cheap-first for `medium`); legend serving scope documented as per-row.

## Impact

- **API**: breaking changes confined to the unreleased API version (`/v1/map/config` removed, catalog response slimmed, no `variants[]`, no inline styles, `version` → `modified`); `layers`/`layers/{slug}`/`slots` added; snapshot regenerated; contract tests pin chains, ETag/304 behavior, envelope and fieldset support.
- **Frontend** (follow-up PR in wodore-frontend-quasar, not this change): basemap store rewires onto `/v1/map/layers`; the Martin-catalog fetch path, its persisted cache, `STYLE_VERSION` and client-side `pickVariant` are deleted; overlay store consumes `modified`.
- **Clients pinned to old versions**: served via the existing ApiVersion downgrade transforms as usual.

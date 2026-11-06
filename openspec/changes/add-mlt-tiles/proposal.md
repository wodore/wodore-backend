# Proposal: add-mlt-tiles

## Why

All Martin vector sources (huts, geoplaces, availability, contours) are served
exclusively as MVT (`.pbf`). The MapLibre Tile format (MLT) v1 is now stable:
natively decoded by MapLibre GL JS ≥ 5.12 and MapLibre Native, with
whole-planet tiles 4–8 % smaller than *gzipped* MVT and 2.3–3.7× faster to
decode — a direct win for the `low` device-spec tier. Martin ≥ 1.9 can convert
MVT→MLT at serve time (no database function or archive changes). MLT v2 is
experimental and explicitly out of scope.

## What Changes

- **Generic `.mlt` URL space, router-owned**: every Martin source gets an
  optional second URL space — `/{source}/{z}/{x}/{y}.mlt` — served by a
  single source-agnostic tile-router route (incl. composite `a,b` and
  function sources), which strips
  the extension and proxies to Martin with
  `Accept: application/vnd.maplibre-tile` (Martin's own URL extensions are
  cosmetic: any `.{ext}` 301-redirects to the extension-less URL, verified
  in Martin's serving code). Chosen over pure Accept-negotiation because
  **no released MapLibre client sends the header** (verified:
  `maplibre-gl@6.15.0` dist lacks it; GL JS #7483 merged on main but
  unreleased, never 5.x; Native #4231 open) and because distinct URLs make
  every cache layer (browser, router, edge) variant-safe by construction —
  no `Vary` (Martin sets none anyway) and no Accept-keyed cache config.
  Query strings (`?v=`, availability params) are preserved by the rewrite.
  A `.mlt` URL always yields MLT bytes or an explicit refusal — never
  silently-wrong MVT; conversion is implicit on Martin ≥ 1.16 (verified
  live on 1.16.1), config-gated (`convert_to_mlt`) below. nginx in front
  is not a new dependency: the router already is the single tile origin
  in dev (Martin has no host port), staging and prod (edge nginx).
- **Martin serve-time conversion**: `convert_to_mlt: auto` on the huts
  source in `tile_server/config/martin.yaml` (the template `martin_sync`
  deploys) — required on Martin < 1.16, no-op on ≥ 1.16 where conversion
  is implicit. Every existing MVT URL and client keeps receiving MVT
  bytes unchanged. Minimum Martin 1.9.0 (dev compose is on 1.16.1 via
  `latest`; the production image pin must be verified/bumped).
- **Style-side opt-in (the client-visible scoping)**: vector sources in
  `MapLayer.style` documents may carry `"encoding": "mlt"` with a `.mlt`
  tiles template. Phase 1 opts in the **huts overlay source** only;
  contours/hillshade stay MVT (their tiles are warm-cached at the prod
  edge — deferred). The style rendering pipeline must preserve the
  `encoding` property verbatim through both resolved and tokenized modes.
- **No transport compression over MLT**: router/edge gzip-brotli lists must
  exclude `application/vnd.maplibre-tile` (MLT is already
  lightweight-compressed; heavy compression negates the decode-speed gain).
- **No frontend header shim**: the frontend needs only maplibre-gl ≥ 5.12 —
  the style document alone selects format via its URLs; no
  `transformRequest`, no release sequencing.
- **No breaking API change**: styles endpoint and catalog unchanged; MVT
  tile URLs unchanged; MLT is additional URL space.

## Capabilities

### New Capabilities
- `tile-format-negotiation`: explicit `.mlt` URL space served via
  router→Martin Accept rewrite — conversion scope, Martin version floor,
  query-string preservation, URL-distinct cache isolation, and
  no-compression rules for MLT bytes.

### Modified Capabilities
- `map-style-api`: the served style documents SHALL preserve a vector
  source's `encoding` property (`mlt` or absent) through both resolved and
  tokenized modes — new requirement on the style rendering pipeline.

## Impact

- `tile_server/tile-router.conf.template` — one generic `.mlt` location
  (any source) with query-string-preserving rewrite + Accept header
  upstream; same
  rewrite in the reference edge-cache doc (`_work/261008…` parity doc);
  no-gzip for the MLT media type.
- `tile_server/config/martin.yaml` — add `convert_to_mlt: auto` to opted-in
  sources (phase 1: huts table); regenerated configs via `app martin_sync`.
- `server/apps/basemaps` — style rendering/serialization must round-trip
  `encoding`; `map_seed` fixture for the huts overlay gains a `.mlt` tiles
  template + `encoding: mlt`.
- Martin image pin (dev = `latest`, already ≥ 1.9; production pin verified).
- Cross-repo: `wodore-frontend-quasar` needs only maplibre-gl ≥ 5.12 (no
  code change if already ≥ 5.12).
- Tests: router rewrite contract tests (MLT bytes, query fidelity, distinct
  cache entries), tile-server config tests, style-API contract tests
  asserting `encoding` preservation.

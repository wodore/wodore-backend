# Design: add-mlt-tiles

## Context

Martin serves all Wodore vector sources (huts table/view, geoplaces +
availability functions, contours postprocessing) straight from Postgres as
MVT (`.pbf`). The tile-router (nginx) publishes `:8075` and stamps vector
tiles `Cache-Control: public, max-age=604800, immutable`; the prod cluster
edge runs a `proxy_cache` in front of Martin for warm terrain tiles
(reference config in `_work/261008_ofm_mtk_parity.md`). The active
`tile-asset-versioning` change adds `?v=<content-version>` to tile URLs and
switches the huts overlay to an inline `tiles` array.

MLT v1 is the stable successor format: decoded natively by MapLibre GL JS
≥ 5.12 (`encoding: 'mlt'` on a vector source) and MapLibre Native
(Android 12.1.0 / iOS 6.20.0, PR #3246; Android 13.4.0 additionally enables
FastPFOR encodings). Martin ≥ 1.9.0 converts MVT→MLT at serve time,
negotiated per request: conversion happens **only** when the client sends
`Accept: application/vnd.maplibre-tile`. **No released MapLibre client sends
that header yet** — verified against the published `maplibre-gl@6.15.0`
dist (zero occurrences of the media type): GL JS PR #7483 is merged to
main (2026-10-21) but deliberately deferred to a v6.x release after 6.15.0
(never 5.x — the maintainers consider new request headers potentially
breaking), and Native PR #4231 is still open. An `encoding: 'mlt'` source
that receives MVT bytes fails to parse, so a `transformRequest` shim is
required until the GL JS release ships. MLT v2 is experimental (no
compatibility promises, `unstable-v2` only) and is excluded. One
forward-compat detail from the merged GL JS code: it sets the header with
`??=`, so a `transformRequest`-provided Accept header is never overwritten
— relevant only if we ever adopt header negotiation later.

Two Martin internals (verified in `martin/src/srv/tiles/content.rs` on
main) shape the design: (a) any tile URL extension is cosmetic —
`/{source}/{z}/{x}/{y}.{ext}` 301-redirects to the extension-less URL and
format selection is purely Accept-header based; (b) Martin sets **no
`Vary` header** on tile responses (only Content-Type, ETag,
Content-Encoding). Additionally, on Martin main the MVT↔MLT conversion is
becoming implicit (no `convert_to_mlt` config needed; the config remains
as a scoping/disabling knob), and Martin's internal tile cache already
keys on the accepted format, so its own cache is variant-safe.

The dev compose tracks `ghcr.io/maplibre/martin:latest` (≥ 1.9 already);
the production image pin lives outside this repo and must be verified.

## Goals / Non-Goals

**Goals:**

- Serve MLT v1 on **distinct, explicit `.mlt` URLs** through a
  **source-generic router route**; MVT URLs and bytes remain byte-identical
  for every existing client (zero-risk enable). Adding a source later is
  two line changes (martin.yaml opt-in + style), never a router change.
- Opt in per style source, pilot on the huts overlay; per-source rollback
  is a style-row edit.
- Cache isolation by URL construction: no `Vary` machinery, no
  Accept-keyed cache config — every cache in the stack (browser, router,
  edge) already keys on URL.
- No database function changes; no archive generation; no frontend header
  shim (frontend needs only maplibre-gl ≥ 5.12, which can decode `encoding:
  'mlt'` sources since 5.12.0).

**Non-Goals:**

- MLT v2 (experimental).
- Pre-generated MLT archives / `ST_AsMLT` (doesn't apply to live function
  sources like availability `date`/`days` params).
- Opting in contours + hillshade in phase 1 (mechanism is generic and
  ready; their tiles are edge-warm and the pilot huts source comes first).
- Frontend implementation (cross-repo, `wodore-frontend-quasar`) — none
  needed beyond maplibre-gl ≥ 5.12.

## Decisions

### D1: Serve-time conversion, not archives

`convert_to_mlt: auto` added **per source** in
`tile_server/config/martin.yaml` (the template `martin_sync` deploys —
it round-trips the file through `yaml.safe_load`/`dump`, so the key
survives regeneration). Scoped per-source rather than at the `postgres:`
level so the opt-in list is explicit and in phase 1 **only the opted-in
source (huts) has `.mlt` URLs referenced by any style**;
an MLT-only Accept on a non-converted source is refused by Martin's
negotiation (406), which is explicit and cache-safe. Alternative —
generating MLT into MBTiles/PMTiles — rejected: our sources are live SQL
functions with query params; archives would freeze them. CPU cost of
per-request conversion is acceptable (Martin documents ~10k tiles/s for
size-optimized encoding; huts traffic is modest), and edge caching of the
converted response (keyed correctly, D3) amortizes it further for warm
tiles.

### D2: Generic `.mlt` URL space owned by the tile-router (not Accept negotiation)

Every Martin source (table, view, function, composite `a,b`) has an
optional second URL space: `/{source}/{z}/{x}/{y}.mlt`. The tile-router
matches the `.mlt` suffix **generically**
(`location ~ ^/(?<mlt_src>[A-Za-z0-9_,]+)/(?<mlt_z>\d+)/(?<mlt_x>\d+)/(?<mlt_y>\d+)\.mlt$`),
strips the extension, and proxies to Martin's canonical extension-less
URL with `proxy_set_header Accept application/vnd.maplibre-tile` —
Martin converts at serve time. This mirrors the existing `/raster/*` →
mapproxy rewrite pattern in the same conf: one route, no per-source
nginx map to maintain. **The client-visible opt-in is the served style**
(tiles template + `encoding`); Martin-side, conversion is **implicit on
Martin ≥ 1.16** (verified live on 1.16.1: any Postgres source converts
on a `.mlt` request), so the `convert_to_mlt` entry in `martin.yaml` is
a compatibility belt for pre-1.16 deployments where conversion is
config-gated — a no-op on current Martin. A `.mlt` request therefore
always yields MLT bytes (or an explicit 406 where conversion is
disabled) — never silently-wrong MVT. MVT keeps the existing URLs
untouched everywhere.

nginx in front is not a new dependency — the router already is the single
tile origin in every environment: the dev compose gives Martin no host
port (the router publishes :8075), and prod/staging serve tiles through
the edge nginx cache tier. The one exception is lane dev
(`lane-martin.sh` runs Martin directly, no router): `.mlt` URLs are not
exercisable there — lane verification uses extension-less URLs + an
explicit Accept header against lane Martin, and `.mlt`-through-router
testing happens against the shared dev router.

Rationale over pure Accept-negotiation (the alternative, and MapLibre's
long-term direction — GL JS #7483 merged, Native #4231 in flight):

- **No client coordination**: no released GL JS sends the header; with
  `.mlt` URLs the style document alone selects the format. The frontend
  needs zero changes beyond maplibre-gl ≥ 5.12 — no `transformRequest`
  shim, no release sequencing.
- **Cache isolation by construction**: browser, router `proxy_cache` and
  edge all key on URL — separate URLs can never cross-serve variants, so
  no `Vary` (which Martin doesn't even set) and no Accept-in-cache-key
  machinery.
- **No transition window**: a client flipping from MVT to MLT gets new
  URLs in the served style; its old immutable cache entries are simply
  not requested. Under header negotiation the same URL + `?v=` (which
  versions *data*, not frontend) would risk stale-variant hits for up to
  7 days.
- **Rejected alternative — Accept in the cache key**: mapping
  `$http_accept` to a binary variant (`mlt`/`mvt`) and folding it into
  `proxy_cache_key` is correct for nginx (never hash the raw header —
  client-controlled strings fragment the cache and invite cache
  pollution), but it only fixes the server-side caches. The browser layer
  would additionally need `Vary: Accept` (Martin sends none; added at the
  router), which only protects entries cached *after* the change — the
  first MVT→MLT rollout still serves stale pre-Vary variants for up to 7d
  unless a `?v=` bump is coupled to the frontend release. It must also be
  replicated identically in the dev router and the prod edge, and it
  still requires the client header shim. Five coordinated mechanisms vs
  one generic route.

Trade-off: the rewrite is ours to maintain (router template + edge
reference), and Martin itself never serves `.mlt` paths — a direct
Martin hit on `/{source}/z/x/y.mlt` (bypassing the router: lane Martin,
the compose network, Martin's web UI) 301-redirects to the extension-less
URL and returns MVT. All external traffic goes through the router, so this
only affects internal/admin use; documented. When clients eventually
send Accept headers natively, the mechanism keeps working unchanged (the
router pins the header for `.mlt` paths regardless), and migrating to
pure negotiation later is a style-only change.

### D3: Query-string preservation in the rewrite

The rewrite MUST forward the query string (rewrite-with-`break` +
variable `proxy_pass` keeps the original args; explicit
`$is_args$args` if a literal URI is ever used) — both the `?v=` content
version (tile-asset-versioning) and the availability function's runtime
params live there. The default `proxy_cache_key`
(`$scheme$proxy_host$request_uri`) already includes the full original
URL (with `.mlt`) and args, so MVT and MLT entries are distinct keys with
no extra config; `Vary` is not used at all (nginx `proxy_cache` ignores
it for keying anyway, and no shared URL exists for browsers to confuse).

### D4: Opt-in lives in the style documents

`encoding: 'mlt'` is authored on the vector source inside `MapLayer.style`
(seed: `map_seed`), and the backend style pipeline must round-trip it
(`map-style-api` delta). No global backend flag: the styles *are* the
per-source switch, rollback is data, and non-Wodore clients consuming the
same styles see the encoding declaration only if they opt in.

### D5: No transport compression over MLT

MLT embeds lightweight compression (FastPFOR/FSST); gzipping on top erases
the decode-speed benefit. Router/edge gzip lists must exclude
`application/vnd.maplibre-tile`.

### D6: Rollout sequencing (each step independently revertible)

1. **Router `.mlt` route** — add the rewrite (inert until Martin converts
   and styles reference it; a `.mlt` request before the Martin config
   lands would get MVT bytes back — the route is only referenced by styles
   in step 3).
2. **Martin config** — `convert_to_mlt: auto` on the huts source
   (inert: no URL requests MLT yet). Adding further sources later is
   martin.yaml + style only — the router route is already generic.
3. **Style opt-in** — `encoding: 'mlt'` + `.mlt` tiles template on the
   huts overlay source; served styles now point clients at the new URLs.

Each step alone is harmless; removing any one breaks the chain. Rollback
of the client-visible behavior is a style-row edit (MVT URLs return
immediately).

## Risks / Trade-offs

- [Rewrite drops the query string → `?v=`/`date` lost → cache busting and
  availability filtering break] → `$is_args$args` in `proxy_pass`; router
  contract test asserting `.mlt` requests reach Martin with identical
  query strings.
- [Direct Martin access on `.mlt` URLs (bypassing the router) 301s to the
  extension-less URL and serves MVT to an MLT-decoding client] → external
  traffic only ever sees router URLs (styles carry them); documented as an
  internal-use caveat.
- [Cache cross-serves a variant] → structurally impossible: MVT and MLT
  are distinct URLs at every cache layer (browser immutable cache, router,
  edge `proxy_cache`).
- [Client sets `encoding: 'mlt'` but fetches MVT URLs] → only possible if
  a style mixes template and encoding; contract test pins the seed pairing
  (`.mlt` template ⇔ `encoding: 'mlt'`).
- [Conversion CPU on hot tiles] → scoped rollout; measure in staging;
  router/edge caching of the converted response (distinct URL) absorbs
  repeats.
- [Prod Martin pin < 1.9 ignores/errs the conversion] → verify pin as an
  explicit task; `martin_sync` regeneration test asserts the config key
  survives (fail-fast at sync time, not serve time).
- [Merge proximity to `tile-asset-versioning` (same files: martin.yaml,
  router, huts source style)] → sequence after it lands or rebase
  deliberately; the `.mlt` templates must be recognized by its `?v=`
  injection (martin-origin URL match).

## Migration Plan

1. Verify prod Martin ≥ 1.9.0 (bump pin if needed) — outside this repo.
2. Land the router `.mlt` route (with `$is_args$args` preservation and
   no-gzip for the MLT media type) and amend the edge reference config
   (same rewrite at the edge); MVT-only world, no behavior change yet.
3. Land `convert_to_mlt: auto` on the huts source in
   `tile_server/config/martin.yaml`; run `app martin_sync`; restart Martin
   (config loads at startup).
4. Style opt-in for huts overlay via seed/regeneration (`.mlt` tiles
   template + `encoding: 'mlt'`); staging verification (map renders,
   query-string fidelity, size comparison); frontend needs only
   maplibre-gl ≥ 5.12 — no header shim.
5. Rollback ladder: revert style row (instant, MVT URLs return) → remove
   router route + config key (martin restart).

## Open Questions

- Exact prod Martin image pin/version — where is it declared (k8s
  manifests, other repo) and is it already ≥ 1.9.0?
- Should contours/terrain follow in phase 2 (add `.mlt` routes + style
  opt-in once the huts pilot is stable in prod)?
- Migrate to pure Accept negotiation later (once GL JS/Native send headers
  natively and Martin's implicit conversion ships in a stable release),
  or keep the URL-based mechanism as the permanent interface?
- Do we want a measured baseline (tile bytes, low-tier decode time) from
  staging before widening opt-in beyond the huts source?

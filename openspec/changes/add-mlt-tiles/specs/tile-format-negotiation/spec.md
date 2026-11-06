# tile-format-negotiation Delta

## ADDED Requirements

### Requirement: Generic explicit MLT URL space

The tile-router SHALL serve MLT v1 for **any** Martin source on explicit
`.mlt` URLs via a single source-agnostic route: `/{source}/{z}/{x}/{y}.mlt`
(including composite `a,b` source lists and function sources) is rewritten
to Martin's canonical extension-less URL with
`Accept: application/vnd.maplibre-tile`. The Martin config deployed by
`martin_sync` SHALL keep conversion available for the opted-in sources
(`convert_to_mlt` — required on Martin < 1.16, a no-op on Martin ≥ 1.16
where conversion is implicit and verified live on 1.16.1); the deployed
Martin version SHALL be ≥ 1.9.0. Existing MVT URLs (`.pbf` or
extension-less) SHALL keep serving MVT bytes unchanged.

#### Scenario: MLT URL returns MLT for an opted-in source

- **WHEN** `/{source}/{z}/{x}/{y}.mlt` is requested through the tile-router for a source with conversion enabled
- **THEN** Martin receives the extension-less URL with `Accept: application/vnd.maplibre-tile` and the response is an MLT v1 tile

#### Scenario: A `.mlt` URL never yields MVT bytes

- **WHEN** a `.mlt` URL is requested for any Martin source
- **THEN** the response is MLT (converted on demand — implicit on Martin ≥ 1.16, config-gated below) or an explicit refusal (406 where conversion is disabled) — never silently-wrong MVT bytes

#### Scenario: Only the literal `.mlt` suffix selects MLT

- **WHEN** a tile is requested extension-less or with any extension other than `.mlt` (`.pbf`, `.mvt`, …) and no MLT accept header
- **THEN** the router does not intervene (Martin serves extension-less directly and 301-redirects other extensions to it) and the client receives MVT bytes — no URL form other than `.mlt` yields MLT

#### Scenario: Client-sent MLT accept headers on MVT URLs stay consistent

- **WHEN** a future client natively sends format-matched Accept headers (GL JS #7483: `application/x-protobuf` on MVT sources, `application/vnd.maplibre-tile` only on `encoding: 'mlt'` sources) while fetching extension-less MVT URLs
- **THEN** the declared capability matches the source format and MVT is served — no unintended conversion on non-`.mlt` URLs

#### Scenario: Query strings survive the rewrite

- **WHEN** a `.mlt` request carries query parameters (`?v=` content version, availability runtime params)
- **THEN** the upstream Martin request carries the identical query string

#### Scenario: Config survives regeneration

- **WHEN** `martin_sync` regenerates the target `martin.yaml` from `tile_server/config/martin.yaml`
- **THEN** the `convert_to_mlt` settings are present on the authored sources

### Requirement: Format-distinct cache entries

MVT and MLT representations SHALL be served on distinct URLs so that
every cache layer (browser immutable cache, tile-router `proxy_cache`,
edge cache) isolates the variants by its existing URL-based keying. No
`Vary` header machinery and no Accept-header cache-key components SHALL
be required for correctness.

#### Scenario: Variants cannot cross-contaminate

- **WHEN** a client caches `/{source}/7/64/43.mlt?v=1` and another (or the same, later) client fetches `/{source}/7/64/43.pbf?v=1`
- **THEN** each URL yields its own format's bytes from every cache layer, independently of request headers

### Requirement: No transport compression over MLT

Router and edge compression configuration SHALL NOT apply gzip or brotli
to responses with the MLT media type (`application/vnd.maplibre-tile`);
MLT bodies SHALL be served with their built-in lightweight compression
only.

#### Scenario: MLT response is not gzipped

- **WHEN** a client requests a `.mlt` tile with `Accept-Encoding: gzip`
- **THEN** the response body is not gzip-encoded

### Requirement: Scoped phase-1 advertisement

The mechanism SHALL be generic for all sources, but the client-visible
opt-in SHALL be the served style documents: phase 1 advertises `.mlt`
URLs (tiles template + `encoding: 'mlt'`) only on the huts overlay
source. Adding a source in a later phase SHALL require only style
changes (plus a Martin config entry for deployments on Martin < 1.16),
never a router change.

#### Scenario: Phase 1 advertises exactly one MLT source

- **WHEN** the phase-1 styles are served
- **THEN** only the huts overlay style carries `encoding: 'mlt'` with `.mlt` tile URLs; no other served style points any client at a `.mlt` URL

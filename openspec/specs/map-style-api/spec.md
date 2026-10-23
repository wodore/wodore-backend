# map-style-api Specification

## Purpose
TBD - created by archiving change map-layer-catalog. Update Purpose after archive.
## Requirements
### Requirement: Style endpoint — resolved mode (default)

The system SHALL serve `GET /v1/map/styles/{slug}.json` returning a complete, plain MapLibre style with `version: 8`: parameter tokens substituted with defaults, environment secrets (API keys held in backend configuration) substituted server-side, and all sprite, glyph, and tile URLs absolutized to their serving origins. The response SHALL contain no unresolved `"{{...}}"` tokens and no root-relative URLs.

#### Scenario: Any-client consumption

- **WHEN** a client without any Wodore-specific machinery fetches the resolved style
- **THEN** it is a valid MapLibre style: version 8, absolute sprite/glyph URLs, defaults baked in

#### Scenario: Env substitution is server-side

- **WHEN** a `style_url` or style references an environment secret (e.g. a MapTiler key)
- **THEN** the served document contains the resolved value in both resolved and tokenized modes, and the secret is never exposed as an overridable parameter

### Requirement: Style endpoint — tokenized mode

The system SHALL support `?mode=tokenized` returning the style with parameter tokens intact (for clients that apply user overrides) while environment secrets remain resolved. Parameter schemas for resolution SHALL be available from the catalog. Runtime-scope parameters (e.g. `{{date}}`) SHALL remain client-side; in resolved mode their declared default is substituted so the document stays fetchable.

#### Scenario: Tokens survive, env does not

- **WHEN** a tokenized style is served
- **THEN** parameter token nodes are present as-is while no environment secret token appears anywhere in the document

### Requirement: Variant selection

The layers, layer-detail, style and catalog endpoints SHALL resolve `spec=`
with the explicit chain — `low → medium → high`, `medium → low → high`,
`high → medium → low` — after an exact match, falling back to the single
existing variant. The response SHALL report which spec was served. Resolution
SHALL be server-side only; clients express the wanted tier and never select
among variants.

#### Scenario: Medium degrades cheaply

- **WHEN** `spec=medium` is requested and the layer exists at `low` and `high`
- **THEN** the `low` variant is served and reported

#### Scenario: Both-direction fallback

- **WHEN** `spec=low` is requested but only `high` exists (or `spec=high` but only `low`)
- **THEN** the existing variant is served with its spec reported in the response metadata

### Requirement: Caching and API contract

The layers, layer-detail, slots, style and catalog responses SHALL carry a
strong ETag and `Cache-Control: public, max-age=0, must-revalidate,
stale-if-error=604800`. The layers/slots ETag SHALL fold an exact catalog
version (max `modified` + counts over every model the payload serializes,
memoized at most 10 seconds), `lang`, `spec`, `role`, `show`, the sparse
fieldset selection and the resolved API version; rendered bodies SHALL be
cached keyed by that version (time-based page caching is removed). The
breaking shape changes (`/v1/map/config` removed, catalog slimmed, no
`variants[]`, no inline styles, `version` renamed `modified`) SHALL be
folded into the unreleased API version with regenerated snapshot and
contract tests; no new API version is created.

#### Scenario: One-reload freshness

- **WHEN** a layer's `show` flag changes and an online client reloads
- **THEN** the conditional request answers non-304 with current data — no
  time window applies anywhere in the chain

#### Scenario: Version-keyed body cache

- **WHEN** any serialized model row changes
- **THEN** the catalog version changes, the previous body cache entries are
  unreachable by key, and the new body renders once

### Requirement: Martin style-serving retirement

`martin_sync` SHALL stop copying `tile_server/styles/` and SHALL NOT configure a styles path in `martin.yaml`; Martin SHALL continue to serve vector tiles, sprites, and fonts. The cutover SHALL be ordered so styles exist in the registry (seeded) before Martin's style routes are dropped.

#### Scenario: Sync output has no styles

- **WHEN** `martin_sync` runs after the cutover
- **THEN** the target directory contains no `styles/` output and the generated martin configuration has no styles path

#### Scenario: Seed before cutover

- **WHEN** the deploy sequence runs
- **THEN** `map_seed` provisions styles into the registry before any Martin style route is removed, so no consumer observes a missing style

### Requirement: Layers endpoint

The system SHALL serve `GET /v1/map/layers` returning the generic
collection envelope `{"data": [...], "count": N}` with exactly one
**resolved** layer per slug — no
`variants[]` array, no inline style documents. Each entry SHALL carry the
served `spec` (fallback applied) and a `style_url` resolved for that spec, the
layer's `modified` (ISO 8601) as the content version, and the resolved row's
spec-scoped fields (parameters, attributions, legend, config, interaction,
anchors) alongside the slug-scoped identity fields. The endpoint SHALL accept
`lang`, `spec` (wanted tier), `role`, `show` (opt-in visibility filter,
default unfiltered) and sparse fieldset selection
(`fields[map_layers]=…`).

#### Scenario: Server-side spec resolution

- **WHEN** `?spec=medium` is requested and the layer exists at `high` and `low`
- **THEN** the entry carries `spec: "low"` and a `style_url` with `spec=low`,
  and no `variants` key is present

#### Scenario: Hidden fallbacks stay resolvable

- **WHEN** `layers` is requested without a `show` filter
- **THEN** hidden basemaps (`show=false`) are included, because clients
  resolve basemap fallback chains against them

#### Scenario: Sparse picker view

- **WHEN** `?fields[map_layers]=slug,name,icon,order,show,is_default,spec,style_url,modified&role=basemap&show=true` is requested
- **THEN** the response contains only those fields per layer

### Requirement: Layer detail endpoint

The system SHALL serve `GET /v1/map/layers/{slug}` returning the same
resolved layer object as the collection entry, accepting `lang`, `spec` and
sparse fieldsets, with a per-layer ETag folding the layer's `modified`, the
served `spec` and `lang`.

#### Scenario: Per-layer revalidation

- **WHEN** the layer row changes and a client re-requests with the previous
  `If-None-Match`
- **THEN** the response is `200` with a new ETag; unchanged layers answer `304`

### Requirement: Slots endpoint

The system SHALL serve `GET /v1/map/slots` returning the generic collection
envelope `{"data": [{slug, label, order}], "count": N}`; the slot list SHALL
NOT be part of the layers payload.

#### Scenario: Slots out of band

- **WHEN** `layers` is requested
- **THEN** the response `data` contains only layer objects and carries no
  slot entries

### Requirement: Martin-parity catalog

`GET /v1/map/catalog` SHALL serve `{"styles": {"<slug>": {"name", "path"}}}`
with `path` resolved for the requested `spec`. It SHALL NOT carry selector
metadata beyond `name` — it is a Martin-compatible debug view, not an
application data source.

#### Scenario: Slim entry

- **WHEN** the catalog is requested
- **THEN** every entry has exactly the keys `name` and `path`

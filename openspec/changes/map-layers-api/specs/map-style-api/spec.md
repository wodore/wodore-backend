## REMOVED Requirements

### Requirement: Catalog endpoint

**Reason**: replaced by `GET /v1/map/layers` (resolved layers, server-side spec
selection) and the Martin-parity `GET /v1/map/catalog`; `/v1/map/config` is
removed. See the ADDED requirements below.

## ADDED Requirements

### Requirement: Layers endpoint

The system SHALL serve `GET /v1/map/layers` returning a collection envelope
`{"layers": [...]}` with exactly one **resolved** layer per slug — no
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

The system SHALL serve `GET /v1/map/slots` returning
`{"slots": [{slug, label, order}]}`; the slot list SHALL NOT be part of the
layers payload.

#### Scenario: Slots out of band

- **WHEN** `layers` is requested
- **THEN** the response contains no `slots` key

### Requirement: Martin-parity catalog

`GET /v1/map/catalog` SHALL serve `{"styles": {"<slug>": {"name", "path"}}}`
with `path` resolved for the requested `spec`. It SHALL NOT carry selector
metadata beyond `name` — it is a Martin-compatible debug view, not an
application data source.

#### Scenario: Slim entry

- **WHEN** the catalog is requested
- **THEN** every entry has exactly the keys `name` and `path`

## MODIFIED Requirements

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

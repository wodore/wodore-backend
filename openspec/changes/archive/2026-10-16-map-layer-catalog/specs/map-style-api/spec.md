## ADDED Requirements

### Requirement: Catalog endpoint

The system SHALL serve `GET /v1/map/catalog` with `lang` and optional `role` filters, returning per-layer metadata only: identity (slug, spec variants, role), i18n labels/descriptions, icon and badge URLs, slot, order and visibility flags, zoom bounds, parameter schemas (slug, kind, label, description, default, constraints), minimal category projections, coverage bounds, anchors and basemap extras, attribution/license projections, and — for layers with large styles — the style endpoint URL. The catalog SHALL NOT inline base-map style documents.

#### Scenario: Payload stays light

- **WHEN** the catalog includes a layer whose style document exceeds a small inline threshold (e.g. `wd-outdoor-base-mtk`, 317 KB)
- **THEN** the entry carries a `style_url` pointing at the style endpoint instead of the style document

#### Scenario: Language and cache

- **WHEN** the catalog is requested with a different `lang`, or any underlying layer/parameter/category row changes
- **THEN** the ETag changes and the response is served with `Cache-Control` appropriate for anonymously cacheable content

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

The style and catalog endpoints SHALL accept `spec=` selecting the device-tier variant with the fallback rule: exact match, else nearest available tier, else the single existing variant. The response SHALL report which spec was served.

#### Scenario: Both-direction fallback

- **WHEN** `spec=low` is requested but only `high` exists (or `spec=high` but only `low`)
- **THEN** the existing variant is served with its spec reported in the response metadata

### Requirement: Caching and API contract

Style responses SHALL carry an ETag folding content hash, `lang`, and registry state, plus `Cache-Control` with a `v` cache-buster derived from the layer's `updated_at`. The endpoints SHALL be additive: registered in the API versioning system without creating a `VersionChange`, with contract tests and an API snapshot committed.

#### Scenario: Cache bust on update

- **WHEN** a layer's style or parameters change
- **THEN** the layer's `updated_at`-derived `v` changes and the ETag of the style response changes

#### Scenario: No version bump

- **WHEN** the change ships
- **THEN** the API version registry is unchanged (additive endpoints only) and contract tests pin request/response shapes

### Requirement: Martin style-serving retirement

`martin_sync` SHALL stop copying `tile_server/styles/` and SHALL NOT configure a styles path in `martin.yaml`; Martin SHALL continue to serve vector tiles, sprites, and fonts. The cutover SHALL be ordered so styles exist in the registry (seeded) before Martin's style routes are dropped.

#### Scenario: Sync output has no styles

- **WHEN** `martin_sync` runs after the cutover
- **THEN** the target directory contains no `styles/` output and the generated martin configuration has no styles path

#### Scenario: Seed before cutover

- **WHEN** the deploy sequence runs
- **THEN** `map_seed` provisions styles into the registry before any Martin style route is removed, so no consumer observes a missing style

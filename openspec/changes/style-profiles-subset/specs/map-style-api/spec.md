## MODIFIED Requirements

### Requirement: Variant selection

The layers, layer-detail, style and catalog endpoints SHALL resolve `spec=`
with the explicit chain — `low → medium → high`, `medium → low → high`,
`high → medium → low` — after an exact match, falling back to the single
existing variant. The response SHALL report which spec was served.
Resolution SHALL be server-side only; clients express the wanted tier and
never select among variants.

The endpoints SHALL additionally accept an optional capability parameter
`profile=full|subset`. Omitted, resolution SHALL be profile-agnostic
(current behavior — clients that predate the parameter are unaffected).
`profile=full` SHALL resolve within the tier chain preferring `full` then
`subset` per tier — the device tier is respected before format richness,
and a `subset` variant is a valid full MapLibre style by construction.
`profile=subset` SHALL resolve `subset` variants only, walking the same
tier chain, and SHALL NEVER serve a `full` variant (a slug without any
`subset` variant is absent from collections and answers 404 on the
detail/style endpoints). The response SHALL report the served `profile`
and the served variant's rules `version`. `style_url` SHALL append the
`profile=` query parameter **only when the request carried the
parameter** — a request without `profile` produces byte-identical
payloads to today's. Cache identity SHALL fold the parameter in
automatically: the collection/detail endpoints' ETags hash every query
parameter (`etag_page`), and the style endpoint's rendered-body cache
is keyed per resolved row — honoring `profile` in variant resolution
(including the style endpoint, which today reads only `spec`) is what
keeps a `?profile=subset` body from ever being served from a
`?profile=full` cache entry or vice versa.

#### Scenario: Medium degrades cheaply

- **WHEN** `spec=medium` is requested and the layer exists at `low` and `high`
- **THEN** the `low` variant is served and reported

#### Scenario: Both-direction fallback

- **WHEN** `spec=low` is requested but only `high` exists (or `spec=high` but only `low`)
- **THEN** the existing variant is served with its spec reported in the response metadata

#### Scenario: Format degrades within the tier first

- **WHEN** a `profile=full` client requests `spec=high` and the slug has `subset@high` and `full@medium`
- **THEN** the `subset@high` row is served with `profile: "subset"` reported — the wanted tier wins over format richness

#### Scenario: Subset clients never receive full variants

- **WHEN** a `profile=subset` client requests a slug that has `full@medium` and `subset@low`
- **THEN** the `subset@low` row is served; if no `subset` variant exists at any tier, the slug is absent from the collection and the style endpoint answers 404

#### Scenario: Omitted profile is today's behavior

- **WHEN** a client sends no `profile` parameter
- **THEN** resolution walks the tier chain profile-agnostically and the
  response is byte-identical to today's, except the additive
  `profile`/`version` entry fields reporting what was served (`style_url`
  gains no `profile=` parameter)

#### Scenario: Profile folds into cache identity

- **WHEN** the same layer is requested with `?profile=full` and `?profile=subset` and both variants exist
- **THEN** the two responses have distinct ETags and distinct rendered-body cache entries

### Requirement: Layers endpoint

The system SHALL serve `GET /v1/map/layers` returning the generic
collection envelope `{"data": [...], "count": N}` with exactly one
**resolved** layer per slug — no
`variants[]` array, no inline style documents. Each entry SHALL carry the
served `spec` (fallback applied) and a `style_url` resolved for that
spec — appending the `profile=` query parameter only when the request
carried `profile` (omitted stays byte-identical to today) — the layer's
`modified` (ISO 8601) as the content
version, the resolved variant's `profile` (`full` | `subset`) and rules
`version` (style-spec release or subset revision; null for externally
authored `style_url` rows — distinct from the `style_version` cache
token), and the resolved row's
spec-scoped fields (parameters, attributions, legend, config, interaction,
anchors) alongside the slug-scoped identity fields. The endpoint SHALL accept
`lang`, `spec` (wanted tier), `profile` (capability: `full` | `subset`,
optional), `role`, `show` (opt-in visibility filter,
default unfiltered) and sparse fieldset selection
(`fields[map_layers]=…`).

#### Scenario: Server-side spec resolution

- **WHEN** `?spec=medium` is requested and the layer exists at `high` and `low`
- **THEN** the entry carries `spec: "low"` and a `style_url` with `spec=low`,
  and no `variants` key is present

#### Scenario: Resolved profile reported

- **WHEN** `?profile=subset` resolves a slug to its `subset@medium` row
- **THEN** the entry carries `profile: "subset"`, `version: "0.1"`, and a `style_url` whose query includes `profile=subset`

#### Scenario: Hidden fallbacks stay resolvable

- **WHEN** `layers` is requested without a `show` filter
- **THEN** hidden basemaps (`show=false`) are included, because clients
  resolve basemap fallback chains against them

#### Scenario: Sparse picker view

- **WHEN** `?fields[map_layers]=slug,name,icon,order,show,is_default,spec,style_url,modified&role=basemap&show=true` is requested
- **THEN** the response contains only those fields per layer

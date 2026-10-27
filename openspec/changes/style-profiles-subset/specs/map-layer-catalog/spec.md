## MODIFIED Requirements

### Requirement: Layer registry

The system SHALL maintain map layers (`MapLayer`) with a stable `slug`, a device tier `spec` (`low` | `medium` | `high`), a rendering `profile` (`full` | `subset`, default `full`), a rules `version` string, a `role` (`basemap` | `overlay`), i18n name and description (modeltrans), an icon-library reference with an optional badge reference, a slot reference, display order, visibility flags (`is_active`, `show`, `is_default` for basemaps), zoom bounds, and — exactly one of — an inline MapLibre `StyleSpecification` (`style` JSONB) or an externally authored `style_url`. Overlay rows MAY carry a `config` JSONB (filter/legend/settings layout) and interaction hints; basemap rows MAY carry anchors, a preview image, and a `fallback` reference to another basemap layer. The `profile` SHALL name the format richness of the variant's style document — `full` for complete MapLibre styles, `subset` for documents restricted to the subset whitelist (valid full MapLibre styles by construction, renderable by simpler engines) — never a renderer. The `version` SHALL record the rules the document was validated against: the `@maplibre/maplibre-gl-style-spec` release for `full` rows (e.g. `26.4.4`), the subset revision for `subset` rows (e.g. `0.1`); it SHALL be required for inline `style` rows and MAY be empty for externally authored `style_url` rows. The style document's internal `"version": 8` field SHALL remain unchanged for both profiles.

#### Scenario: Style source exclusivity

- **WHEN** a layer is saved with both `style` and `style_url` set, or with neither
- **THEN** the save is rejected with a validation error

#### Scenario: Slug stability across variants

- **WHEN** the same logical layer exists at two device tiers (e.g. `ch-swisstopo-light` at `high` and `low`)
- **THEN** both rows share the slug and differ only in `spec`, and layer identity for groups and preferences remains the slug

#### Scenario: Version records the validation rules

- **WHEN** a `subset` row validated against subset v0.1 and a `full` row validated against style-spec `26.4.4` are served
- **THEN** each carries its own rules `version` (`0.1` / `26.4.4`) while both style documents still declare `"version": 8` internally

#### Scenario: Profile and spec are independent dimensions

- **WHEN** the same slug exists as `(medium, full)` and `(medium, subset)`
- **THEN** both rows are valid variants of one layer, and variant resolution — not the slug — decides which one a given client receives

#### Scenario: Version required for inline styles

- **WHEN** an inline `style` row is saved without a `version`, or an externally authored `style_url` row is saved with one
- **THEN** the first is rejected with a validation error; the second is accepted (external documents are not ours to version)

### Requirement: Device-tier variants

The system SHALL enforce uniqueness of `(slug, spec, profile)`. Variant
selection SHALL be server-side: endpoints resolve the requested `spec`
via the explicit chain `low → medium → high`, `medium → low → high`,
`high → medium → low` after an exact match, falling back to the single
existing variant — a low-tier request with only a `high` variant SHALL
receive it, and vice versa, and a `medium` request with `low` and `high`
available SHALL receive `low`. Resolution SHALL additionally honor the
client's capability profile (`?profile=full|subset`, omitted =
profile-agnostic, preserving current behavior): a `full`-capable client
SHALL prefer `full` then `subset` within each tier of the chain, and a
`subset`-capable client SHALL walk the same tier chain considering
`subset` variants only and SHALL NEVER be served a `full` row — a slug
without any `subset` variant is absent from its resolved views. APIs
SHALL NOT expose variant arrays; each response carries exactly the
resolved variant.

#### Scenario: Duplicate variant rejected

- **WHEN** a second row is saved with an already existing `(slug, spec, profile)` triple
- **THEN** the save is rejected

#### Scenario: Fallback in both directions

- **WHEN** a client requests `spec=low` and only a `high` variant exists (or requests `spec=high` and only `low` exists)
- **THEN** the existing variant is served and the response reports which `spec` was selected

#### Scenario: Medium prefers the cheaper tier

- **WHEN** a client requests `spec=medium` and both `low` and `high` variants exist
- **THEN** the `low` variant is served and its spec reported

#### Scenario: Tier is respected before format richness

- **WHEN** a `profile=full` client requests `spec=medium` and the slug has `subset@medium` and `full@low`
- **THEN** the `subset@medium` row is served (any profile at the wanted tier beats any profile at a degraded tier; within a tier, `full` beats `subset`)

#### Scenario: Subset clients never receive full variants

- **WHEN** a `profile=subset` client requests a slug whose only variants are `full`
- **THEN** no variant is served — the slug is absent from collections and the detail/style endpoints answer 404 — never a `full` document

## ADDED Requirements

### Requirement: Subset profile definition

The system SHALL define a strict subset profile of the MapLibre style
spec (revision `0.1`) such that every `subset` document is a valid full
MapLibre style (`"version": 8`) by construction while remaining
renderable by a Leaflet-class engine. The whitelist SHALL cover:

- **Sources**: `raster` (keys `tiles`, `maxzoom`, `tileSize`,
  `attribution`), `vector` (inline MLT tile URLs via `tiles`, plus
  `minzoom`, `maxzoom`, `attribution`; single `source-layer` consumed by
  layers; no TileJSON `url` links), `geojson` (`data` URL string, with
  `{{token}}` runtime parameter params allowed inline).
- **Layers**: types `raster`, `circle`, `symbol` (sprite-pack icon +
  simple text), each carrying `id`, `source`, `source-layer`, `minzoom`,
  `maxzoom`, `paint` and `layout`; symbol layout is limited to
  `icon-image`, `icon-size`, `icon-allow-overlap`, `text-field`,
  `text-font`, `text-size`, `text-anchor`, `text-offset`; circle/raster
  layers carry no layout keys.
- **Paint properties** (closed set): `circle-color`, `circle-radius`,
  `circle-opacity`, `circle-stroke-color`, `circle-stroke-width`,
  `raster-opacity`, `raster-fade-duration`, `icon-size`, `icon-color`,
  `icon-opacity`, `icon-translate`, `text-size`, `text-color`,
  `text-opacity`, `text-halo-color`, `text-halo-width`, `text-translate`
  (`icon-size`/`text-size` accepted in either the paint or layout slot).
- **Expressions** (recursive, any depth): `get`, `has`, `match`, `case`,
  `in`, `==`, `interpolate` with zoom input only, `literal`; standalone
  `"{{slug}}"` parameter token nodes are valid values.
- **Explicitly excluded**: `feature-state`, `fill` / `fill-extrusion` /
  `line` / `heatmap` layer types, SDF text layout properties (variable
  anchors, letter spacing, …), pitch/terrain/sky, data-driven paint
  outside the whitelist, and any non-whitelisted expression operator or
  source/layer key (including `promoteId` and the vector TileJSON `url`
  form).

Style documents outside the whitelist SHALL be rejected when saved or
seeded with `profile=subset` (see *Style document validation*).

#### Scenario: Raster overlay validates as subset

- **WHEN** a seeded raster overlay style (one raster source with `tiles`/`tileSize`, one raster layer with a `raster-opacity` parameter token) is validated against subset v0.1
- **THEN** it passes: source keys, layer type, paint property and token node are all within the whitelist

#### Scenario: Expressive circle styling validates as subset

- **WHEN** a circle layer uses `case` over `in`/`get` for its color, a `match` on a feature property for another paint property, and `interpolate` over `["zoom"]` with `["linear"]` interpolation for its radius
- **THEN** it passes — the served `transport-stops` and `wd-huts-occupation` shapes are subset-expressible

#### Scenario: Non-whitelisted layer type rejected

- **WHEN** a subset-tagged style contains a `fill` or `line` layer
- **THEN** validation fails naming the offending layer

#### Scenario: Non-whitelisted expression rejected

- **WHEN** a subset-tagged style uses `feature-state`, an `image` expression, or an `interpolate` over a non-zoom input
- **THEN** validation fails naming the offending path

### Requirement: Style document validation

The system SHALL validate style documents per profile. `full` inline
styles SHALL be validated against the MapLibre style spec by the `styl`
Rust binary (github.com/navidnabavi/styl) in CI — locally via `cargo
install styl`, in CI via the GitHub Action `navidnabavi/styl@v0.0.4`
with `.stylrc` configuration — and NEVER in the server runtime (no
Node.js or Rust dependency at serve time; serve-time checks stay
structural). `subset` styles SHALL be validated by a pure-Python subset
walker inside the Django app implementing the *Subset profile
definition* whitelist, running at model validation (admin and factory
saves), at seed ingest, and as a CI sweep over every `profile=subset`
row. Structural checks (`version == 8`, sources object, `{id, type}`
layers) SHALL apply to both profiles. The style-spec release validated
against SHALL be recorded as the row's rules `version`.

#### Scenario: Subset violation blocks seed ingest

- **WHEN** `map_seed` (or an admin save) writes a `profile=subset` row whose style uses a non-whitelisted property
- **THEN** the write is rejected with a path-precise validation error

#### Scenario: CI sweeps seeded subset rows

- **WHEN** the CI sweep runs over all `profile=subset` rows and one has drifted outside the whitelist (edited or retagged)
- **THEN** the sweep fails nonzero naming the row and path

#### Scenario: Full fixtures validated by styl in CI

- **WHEN** CI runs the styl job over the inline `full` seed fixtures and one violates the MapLibre style spec
- **THEN** the job fails; the server runtime remains free of any styl/Node dependency

### Requirement: Clustering rendering hints

Cluster rendering hints SHALL live in the overlay's `config` JSONB
(`config.clustering`) — never inside the style document (the MapLibre
spec allows `cluster` only on geojson sources; on a vector source it
would break subset validity). The schema SHALL comprise `enabled`,
`source` (the style source id to cluster), `groupByProperty` (only
features sharing the property value cluster together; features lacking
the property form one null bucket), `radius`, `maxZoom`, and a `bubble`
object carrying either property references (`colorProperty`,
`iconProperty`, `countProperty` — the renderer derives the dominant
value per group) or literal fallbacks (`color`, `icon`). One config
SHALL serve both clustering modes: client-side clustering over the
vector source today, and precomputed DB clusters in the tiles later
(same properties read from cluster features — config unchanged).

#### Scenario: Null bucket

- **WHEN** features lack the `groupByProperty` value entirely
- **THEN** they cluster together in one null bucket rather than unclustered scatter

#### Scenario: One config, two modes

- **WHEN** clustering switches from client-side grouping to precomputed cluster features in the tiles
- **THEN** the same `config.clustering` block drives rendering — no style or config change

#### Scenario: Literal bubble fallbacks

- **WHEN** `bubble` carries literal `color`/`icon` values instead of property references
- **THEN** the renderer uses them directly and consults no feature property

#### Scenario: Malformed clustering block rejected

- **WHEN** a `config.clustering` block is saved with unknown keys or wrong value types
- **THEN** the save is rejected with a validation error naming the key

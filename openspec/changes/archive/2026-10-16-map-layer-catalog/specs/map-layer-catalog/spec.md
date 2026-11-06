## ADDED Requirements

### Requirement: Layer registry

The system SHALL maintain map layers (`MapLayer`) with a stable `slug`, a device tier `spec` (`low` | `medium` | `high`), a `role` (`basemap` | `overlay`), i18n name and description (modeltrans), an icon-library reference with an optional badge reference, a slot reference, display order, visibility flags (`is_active`, `show`, `is_default` for basemaps), zoom bounds, and — exactly one of — an inline MapLibre `StyleSpecification` (`style` JSONB) or an externally authored `style_url`. Overlay rows MAY carry a `config` JSONB (filter/legend/settings layout) and interaction hints; basemap rows MAY carry anchors, a preview image, and a `fallback` reference to another basemap layer.

#### Scenario: Style source exclusivity

- **WHEN** a layer is saved with both `style` and `style_url` set, or with neither
- **THEN** the save is rejected with a validation error

#### Scenario: Slug stability across variants

- **WHEN** the same logical layer exists at two device tiers (e.g. `ch-swisstopo-light` at `high` and `low`)
- **THEN** both rows share the slug and differ only in `spec`, and layer identity for groups and preferences remains the slug

### Requirement: Device-tier variants

The system SHALL enforce uniqueness of `(slug, spec)` and expose all active variants in the catalog. Style serving SHALL select the variant requested via `spec=`, falling back gracefully: exact match, else the nearest available tier, else the single existing variant — a low-tier device with only a `high` variant SHALL receive it, and vice versa.

#### Scenario: Duplicate variant rejected

- **WHEN** a second row is saved with an already existing `(slug, spec)` pair
- **THEN** the save is rejected

#### Scenario: Fallback in both directions

- **WHEN** a client requests `spec=low` and only a `high` variant exists (or requests `spec=high` and only `low` exists)
- **THEN** the existing variant is served and the response reports which `spec` was selected

### Requirement: Parameter registry

The system SHALL maintain map parameters (`MapParameter`) with a unique slug, a `kind`, i18n label and description, a default value, and optional constraints. Kinds SHALL include scalars (`number`, `color`, `boolean`, `enum`, `string`, `date`) and widget kinds whose default is a MapLibre expression subtree (`opacity-curve` first). Layers SHALL reference parameters M2M through a join carrying an optional per-layer default override. Styles SHALL reference parameters as standalone JSON token nodes (`"{{slug}}"`).

#### Scenario: Unknown token rejected

- **WHEN** a style is saved containing a `"{{token}}"` node whose slug is not linked to the layer (or the global registry)
- **THEN** the save is rejected naming the unknown token

#### Scenario: Opacity widget validation

- **WHEN** an `opacity-curve` default or override is saved whose zoom stops are not strictly ascending or whose opacity values fall outside 0–1
- **THEN** the save is rejected

#### Scenario: Shared parameter, per-layer override

- **WHEN** two layers link the same parameter and one sets a per-layer default override
- **THEN** the other layer's served default is unchanged

#### Scenario: Date parameter typing

- **WHEN** a parameter of kind `date` (ISO 8601) is linked to a layer whose style embeds its token in a source URL (e.g. the availability GeoJSON endpoint)
- **THEN** clients refetch that source when the value changes, and resolved-mode serving substitutes the parameter's declared default date

#### Scenario: Override resolution order

- **WHEN** a parameter value is resolved for serving or client application
- **THEN** the most specific value wins: registry default, then authored per-layer override, then user global override, then user per-layer override

### Requirement: Slot registry

The system SHALL maintain insertion slots (`MapSlot`: slug, order, label_i18n) as database rows referenced by layers. The seed SHALL provide `background` and `ways`; additional slots (e.g. a label-level slot for layers rendering above basemap labels) SHALL be addable as data without schema or code changes.

#### Scenario: Adding a slot is data-only

- **WHEN** a curator creates a new slot row and links layers to it
- **THEN** clients place those layers at the slot's order without any backend code change

### Requirement: Category links

The system SHALL link layers to categories through `MapLayerCategory` (category FK, `use` ∈ `filter` | `legend` | `primary`, order). The catalog SHALL embed a minimal stable projection per linked category (slug, identifier, name in the request language, symbol URLs, color) and SHALL resolve defensively: missing or inactive categories are skipped with a warning, never a 500.

#### Scenario: Levels in the projection

- **WHEN** a linked category has children
- **THEN** the projection exposes the hierarchy (parent/child identifiers) so level-aware legends and filters render without additional requests

#### Scenario: Defensive resolution

- **WHEN** a `config` JSONB entry references a category slug that no longer exists
- **THEN** serving skips that entry and logs it, and the endpoint still returns 200

### Requirement: Attribution and licensing

The system SHALL attribute layers via M2M to `Organization` (whose `attribution` and `url` fields are the payload) and MAY attach a `licenses.License` FK. Layers whose style references third-party tile or data sources SHALL carry at least one attribution.

#### Scenario: Deduplicated attribution

- **WHEN** six layers reference swisstopo tiles
- **THEN** they all link the same Organization row and the catalog serializes it once per layer from a single source row

#### Scenario: Missing attribution rejected

- **WHEN** a layer with external raster/vector sources is saved without any attribution link
- **THEN** the save is rejected with a validation error

### Requirement: Coverage and basemap extras

Overlay and basemap rows MAY reference a `MapCoverage` polygon with a `fallback_min_zoom`; the catalog SHALL export the coverage bounds (bbox). Basemap rows MAY reference a `fallback` basemap layer (auto-switch relation) and anchors (insertion points for overlay slots per basemap style).

#### Scenario: Coverage bounds in catalog

- **WHEN** a layer has a coverage
- **THEN** the catalog entry carries its bbox so clients implement country clipping without extra requests

#### Scenario: Fallback relation exposed

- **WHEN** a basemap defines `fallback`
- **THEN** the catalog entry names the fallback layer's slug

### Requirement: Seed and parity

The system SHALL provide an idempotent `map_seed` command provisioning slots, parameters, organization/license links, the current overlays and basemaps (styles as fixture files), and default overlay groups. A parity check SHALL verify that the seeded, resolved style output for previously Martin-served styles equals the Martin-served file modulo URL absolutization.

#### Scenario: Seed is idempotent

- **WHEN** `map_seed` runs twice without model changes
- **THEN** the second run reports no changes

#### Scenario: Parity with Martin-served styles

- **WHEN** the resolved style for `wd-outdoor-base-mtk` is compared with `tile_server/styles/wd-outdoor-base-mtk.json`
- **THEN** they are identical except absolutized sprite/glyph/tile URLs

### Requirement: Map legend registry

The system SHALL maintain legends (`MapLegend`) with ordered sections (`MapLegendSection`: i18n title/description, render type, optional category FK for category-driven sections) and static items (`MapLegendItem`: i18n label/description, color/width that MAY reference parameter tokens, icon ref). Legend links SHALL be M2M to `external_links.ExternalLink` (ordered through `MapLegendLink`). `MapLayer.legend` SHALL reference a legend shared by all spec variants of the layer (slug-level; per-variant divergence is possible but discouraged). The catalog SHALL serialize legends in the frontend-compatible shape with tokens passed through verbatim for client-side resolution.

#### Scenario: Variable-aware legend item

- **WHEN** a legend item's color references a parameter token (e.g. `{{trail_color}}`)
- **THEN** the catalog serves the token verbatim and clients resolve it with the same defaults ∪ user-overrides walk used for styles

#### Scenario: Variants share one legend

- **WHEN** a layer exists in multiple spec variants
- **THEN** all variant rows reference the same legend row and the catalog emits exactly one legend for the slug

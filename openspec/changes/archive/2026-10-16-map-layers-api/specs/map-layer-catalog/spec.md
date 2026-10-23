## MODIFIED Requirements

### Requirement: Device-tier variants

The system SHALL enforce uniqueness of `(slug, spec)`. Variant selection SHALL
be server-side: endpoints resolve the requested `spec` via the explicit chain
`low → medium → high`, `medium → low → high`, `high → medium → low` after an
exact match, falling back to the single existing variant — a low-tier request
with only a `high` variant SHALL receive it, and vice versa, and a `medium`
request with `low` and `high` available SHALL receive `low`. APIs SHALL NOT
expose variant arrays; each response carries exactly the resolved variant.

#### Scenario: Duplicate variant rejected

- **WHEN** a second row is saved with an already existing `(slug, spec)` pair
- **THEN** the save is rejected

#### Scenario: Fallback in both directions

- **WHEN** a client requests `spec=low` and only a `high` variant exists (or requests `spec=high` and only `low` exists)
- **THEN** the existing variant is served and the response reports which `spec` was selected

#### Scenario: Medium prefers the cheaper tier

- **WHEN** a client requests `spec=medium` and both `low` and `high` variants exist
- **THEN** the `low` variant is served and its spec reported

### Requirement: Map legend registry

The system SHALL maintain legends (`MapLegend`) with ordered sections
(`MapLegendSection`: i18n title/description, render type, optional category FK
for category-driven sections) and static items (`MapLegendItem`: i18n
label/description, color/width that MAY reference parameter tokens, icon
ref). Legend links SHALL be M2M to `external_links.ExternalLink` (ordered
through `MapLegendLink`). `MapLayer.legend` SHALL be a per-row (per-spec)
reference; sharing one legend row across a slug's variants SHALL remain the
seed default, and per-spec divergence SHALL be supported without schema
change. APIs SHALL serialize the resolved row's legend in the
frontend-compatible shape with tokens passed through verbatim for
client-side resolution.

#### Scenario: Variable-aware legend item

- **WHEN** a legend item's color references a parameter token (e.g. `{{trail_color}}`)
- **THEN** the layers payload serves the token verbatim and clients resolve it with the same defaults ∪ user-overrides walk used for styles

#### Scenario: Variants share one legend

- **WHEN** a layer exists in multiple spec variants and the curator links all variants to one legend row
- **THEN** every resolved response for that slug emits that same legend

#### Scenario: Per-spec legend divergence

- **WHEN** a curator links the `low` variant to a raster-specific legend and the `high` variant to a vector legend
- **THEN** `?spec=low` and `?spec=high` responses each carry their own legend

# map-style-api Delta

## ADDED Requirements

### Requirement: Amenity overlay popup tile fields

The accommodations overlay and the ten amenity overlay styles (full
and subset profiles) SHALL request `category_identifier` and
`elevation` in their geoplaces tiles `fields` parameter, so individual
tile features carry the popup's paint props (per-kind icon key +
elevation). The tile function SHALL emit `elevation` only when the
`fields` parameter names it (omitted — not null — otherwise; cluster
features never carry it), and the transition-zone twin's individual
features SHALL carry their real `slug` and `max_label_zoom`-gated
`name` instead of empty strings.

#### Scenario: Individual features carry the popup props

- **WHEN** an amenity overlay tile is requested with the overlay's fields list at a zoom with individual (non-cluster) features
- **THEN** those features expose `category_identifier` and, where the place has one, `elevation`

#### Scenario: Non-opting consumers stay byte-identical

- **WHEN** a geoplaces tile is requested without `elevation` in `fields`
- **THEN** its features contain no `elevation` property and the tile bytes are unchanged from before the field existed

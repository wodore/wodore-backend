# Spec Delta: geoplace-category-attributes

## ADDED Requirements

### Requirement: Operating modes via association classifier

The system SHALL allow each `GeoPlaceCategory` association to reference
exactly one classifier category whose parent is `mode` (children:
`standard`, `reduced`). The classifier qualifies the operation mode of
the association. An association without a classifier means "no mode
claimed". The unique constraint SHALL key on
`(geo_place, category, classifier)` with `nulls_distinct=False`, so
one category can carry both the standard and the reduced mode for the
same place.

#### Scenario: Hut with winter room
- **WHEN** a hut with `hut_type_open=accommodation.hut` and
  `hut_type_closed=accommodation.selfhut` is imported from the wodore
  source
- **THEN** the place carries two associations:
  `category=accommodation.hut, classifier=mode.standard` and
  `category=accommodation.selfhut, classifier=mode.reduced`

#### Scenario: Same category under both modes
- **WHEN** a hut's open and closed type are the same category (e.g.
  both `accommodation.unknown`)
- **THEN** two associations coexist — one with `mode.standard`, one
  with `mode.reduced`

#### Scenario: Classifier restricted to mode subtree
- **WHEN** a `GeoPlaceCategory` is saved with a classifier whose parent
  slug is not `mode`
- **THEN** the save is rejected with a validation error

### Requirement: Mode capacities in association extra

The system SHALL store each mode's bed capacity in its association's
`extra` under the key `capacity` (non-negative integer). A capacity the
source does not publish SHALL be omitted, not stored as `null`. Keys
outside the category's schema SHALL be preserved but never written by
imports.

#### Scenario: Capacities written on import
- **WHEN** a hut with 40 open beds and 12 winter beds is imported
- **THEN** the standard association's `extra` is `{"capacity": 40}`
  and the reduced association's `extra` is `{"capacity": 12}`

#### Scenario: Reduced fact without closed type
- **WHEN** a hut publishes `capacity_closed` but its closed type is
  absent or `unknown`
- **THEN** a reduced association is created on
  `accommodation.unknown` carrying `{"capacity": <capacity_closed>}`

#### Scenario: No reduced fact
- **WHEN** a hut has no closed type and no published closed capacity
- **THEN** the place carries only the standard association

#### Scenario: Import path validates too
- **WHEN** `GeoPlace.update_or_create` is called with a schema whose
  category `extra` violates the category's schema or whose classifier
  is outside the `mode` subtree
- **THEN** the association is not written and the validation error is
  raised (Django does not call `clean()` implicitly — the schema path
  invokes the same checks)

### Requirement: Mode category vocabulary

The system SHALL provide a `mode` parent category with children
`standard` and `reduced`, created by data migration and manageable in
the category admin. The identifiers map 1:1 onto the availability
tiles' `dN_type` classification (`standard` | `reduced`).

#### Scenario: Vocabulary exists after migrate
- **WHEN** migrations run on a fresh database
- **THEN** the two `mode.*` categories exist, are active, and carry
  populated `identifier` columns (`mode.standard`, `mode.reduced`)

### Requirement: Category extra schemas (JSON Schema, admin-manageable)

The system SHALL describe each category subtree's `extra` structure
with a JSON Schema (draft 2020-12) stored in the database
(`CategoryExtraSchema`, one per category, resolved own-category-first
with a one-level parent fallback). The initial schema is seeded by
data migration (accommodation parent: `capacity`); afterwards it is
editable in the admin. Schemas SHALL be validated against the JSON
Schema metaschema on save, SHALL NOT set `additionalProperties:
false` (unknown keys are preserved by design), and a corrupt stored
schema SHALL fail open at read time (loud log, no validation) rather
than blocking writes. New optional keys (e.g. water, heating — values
often nullable) can be added without code or DB changes.

#### Scenario: Schema change applies to next write
- **WHEN** an editor adds `water` to the accommodation schema and
  saves an association with `extra={"water": "yes"}`
- **THEN** the value validates and is stored; existing rows are not
  retro-checked

#### Scenario: Corrupt schema fails open
- **WHEN** a stored schema fails to compile
- **THEN** association writes under that category skip schema
  validation (logged loudly) instead of raising

### Requirement: Wodore hut import populates mode associations

The wodore source handler of `import_geoplaces` SHALL import every
active `Hut` via `GeoPlace.update_or_create`, populating base fields,
the standard association from `hut_type_open` + `capacity_open`, and
the reduced association per the rule above (closed type when known,
else `accommodation.unknown` when only `capacity_closed` is
published). Re-runs with `--update` SHALL respect the
protected-fields policy and refresh existing associations per
`(category, mode)`.

#### Scenario: Full import of a hut
- **WHEN** `import_geoplaces -s wodore` runs against a hut with
  name, location, elevation, country, both hut types and both
  capacities
- **THEN** the created GeoPlace has both mode associations with their
  capacities in `extra`

#### Scenario: Protected place untouched
- **WHEN** an imported place has been manually edited
  (`is_modified=true` / protected fields)
- **THEN** a re-import with `--update` skips the protected fields

### Requirement: API exposes association classifier and extra

The GeoPlace search, nearby, and place detail responses SHALL include,
for every category entry, the optional `classifier` (category
identifier or null) and the association `extra` dict, under the
`fields[places]` sparse-fieldset selection. The additive response
change SHALL be registered in the API changelog per `api-conventions`.

#### Scenario: Search result carries attributes
- **WHEN** a client searches for a place whose standard association
  has `extra.capacity=12`
- **THEN** the response's category entry contains the classifier
  identifier and `"extra": {"capacity": 12}`

### Requirement: Admin editing of modes and extra

The GeoPlace admin's category inline SHALL allow editing `classifier`
(autocomplete, scoped to the `mode` subtree) and `extra` (rendered
from the resolved category schema through the JSON-Schema editor;
plain JSON textarea when no schema). `CategoryExtraSchema` SHALL be
admin-editable (seeded from code initially).

#### Scenario: Editor sets reduced capacity
- **WHEN** an editor sets `capacity=8` on a place's reduced-mode
  association in the admin and saves
- **THEN** the association's `extra` contains `capacity: 8` and the
  formset save marks the place `is_modified` with the flat
  `"categories"` protection entry (pre-existing wiring)

### Requirement: Tiles carry association attributes

The `geoplaces_for_tiles` view SHALL expose each category entry's
`extra` and `classifier` identifier to tile consumers (the key lives
inside the categories JSON; martin needs no config change).

#### Scenario: Tile payload includes modes
- **WHEN** tiles are requested at a zoom showing a hut-derived place
- **THEN** the place's category entries in the tile payload include
  the `extra` dict and the `classifier` identifier where set

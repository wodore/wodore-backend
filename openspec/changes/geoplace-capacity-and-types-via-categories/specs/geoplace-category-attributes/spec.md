# Spec Delta: geoplace-category-attributes

## ADDED Requirements

### Requirement: Season classification via association classifier

The system SHALL allow each `GeoPlaceCategory` association to reference
exactly one classifier category whose parent is `season`. The classifier
qualifies how the place operates in its closed season (e.g.
`season.winter_room`). An association without a classifier means
"unknown / not applicable".

#### Scenario: Hut with winter room
- **WHEN** a hut with `hut_type_open=accommodation.hut` and
  `hut_type_closed=accommodation.selfhut` is imported from the wodore
  source
- **THEN** the resulting association is
  `category=accommodation.hut, classifier=season.self_service`

#### Scenario: Classifier restricted to season subtree
- **WHEN** a `GeoPlaceCategory` is saved with a classifier whose parent
  slug is not `season`
- **THEN** the save is rejected with a validation error

### Requirement: Typed capacities in association extra

The system SHALL store bed capacities in `GeoPlaceCategory.extra` under
the keys `capacity_open` and `capacity_closed` (non-negative integers).
Unknown keys SHALL be preserved but never written by imports. A capacity
the source does not publish SHALL be omitted, not stored as `null`.

#### Scenario: Capacities written on import
- **WHEN** a hut with 40 open beds and no published winter beds is
  imported
- **THEN** the accommodation association's `extra` is
  `{"capacity_open": 40}`

#### Scenario: Invalid capacity rejected
- **WHEN** an association is saved with `extra` containing
  `capacity_open: -1` or a non-integer value
- **THEN** the save is rejected with a validation error

### Requirement: Season category vocabulary

The system SHALL provide a `season` parent category with children
`winter_room`, `self_service`, `year_round`, `closed`, and `summer_only`,
created by data migration and manageable in the category admin.

#### Scenario: Vocabulary exists after migrate
- **WHEN** migrations run on a fresh database
- **THEN** the five `season.*` categories exist and are active

### Requirement: Wodore hut import populates category attributes

The wodore source handler of `import_geoplaces` SHALL import every active
`Hut` via `GeoPlace.update_or_create`, populating base fields, the
category from `hut_type_open`, the classifier from `hut_type_closed`
(per the mapping in the change design), and capacities from
`capacity_open`/`capacity_closed`. Re-runs with `--update` SHALL respect
the protected-fields policy.

#### Scenario: Full import of a hut
- **WHEN** `import_geoplaces -s wodore` runs against a hut with
  name, location, elevation, country, both hut types and both capacities
- **THEN** the created GeoPlace has the accommodation category with the
  season classifier and both capacity keys in `extra`

#### Scenario: Protected place untouched
- **WHEN** an imported place has been manually edited
  (`is_modified=true` / protected fields)
- **THEN** a re-import with `--update` skips the protected fields

### Requirement: API exposes association classifier and extra

The GeoPlace search, nearby, and detail responses SHALL include, for
every category entry, the optional `classifier` (category identifier or
null) and the association `extra` dict.

#### Scenario: Search result carries attributes
- **WHEN** a client searches for a place whose accommodation association
  has classifier `season.winter_room` and `extra.capacity_open=12`
- **THEN** the response's category entry contains
  `"classifier": "season.winter_room"` and
  `"extra": {"capacity_open": 12}`

### Requirement: Admin editing of classifier and extra

The GeoPlace admin's category inline SHALL allow editing `classifier`
(autocomplete, scoped to the `season` subtree) and `extra` (with the two
capacity keys rendered as labeled numeric fields).

#### Scenario: Editor sets winter capacity
- **WHEN** an editor sets `capacity_closed=8` on a place's accommodation
  association in the admin and saves
- **THEN** the association's `extra` contains `capacity_closed: 8` and
  the place's protected-fields tracking records the manual edit

### Requirement: Tiles carry association attributes

The `geoplaces_tiles` view SHALL expose each category entry's `extra`
and `classifier` identifier to tile consumers.

#### Scenario: Tile payload includes capacities
- **WHEN** tiles are requested at a zoom showing a hut-derived place
- **THEN** the place's category entries in the tile payload include the
  `extra` dict and the `classifier` identifier where set

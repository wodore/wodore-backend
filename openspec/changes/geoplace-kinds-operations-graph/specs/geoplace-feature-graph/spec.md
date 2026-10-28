# Spec Delta: geoplace-feature-graph

## ADDED Requirements

### Requirement: GeoPlaceRelation semantic edges

The system SHALL provide a `GeoPlaceRelation` model with
`from_place` / `to_place` foreign keys to GeoPlace and a `relation`
foreign key to a `relations/*` category (`part_of`, `near`, `serves`,
`access_point`), storing each one-direction edge exactly once
(reverse queries swap FK direction via `outgoing_relations` /
`incoming_relations`), carrying `confidence` (default 1.0) and
`extra` JSON. Relation choices are constrained to the `relations`
subtree (`limit_choices_to` + validation).

#### Scenario: Forward and reverse traversal
- **WHEN** a relation `hut → part_of → municipality` exists
- **THEN** `hut.outgoing_relations` finds it and
  `municipality.incoming_relations` finds the same edge

#### Scenario: Relation choices are constrained
- **WHEN** a GeoPlaceRelation is created with a category whose parent
  slug is not `relations`
- **THEN** the category is not offered in admin and validation
  rejects it

### Requirement: Relation integrity constraints

GeoPlaceRelation SHALL enforce uniqueness of
`(from_place, to_place, relation)` and reject self-loops via database
constraints.

#### Scenario: Duplicate triple rejected
- **WHEN** the same triple is inserted twice
- **THEN** the second insert fails with a unique-constraint violation

#### Scenario: Self-loop rejected
- **WHEN** a relation with `from_place == to_place` is inserted
- **THEN** the insert fails with a check-constraint violation

### Requirement: Graph lookup performance

GeoPlaceRelation SHALL be indexed on `(from_place, relation)` and
`(to_place, relation)` so traversal needs no spatial operations.

#### Scenario: Indexed traversal
- **WHEN** `get_related_places("part_of")` is queried
- **THEN** the composite indexes serve it; no geometry function runs

### Requirement: GeoPlace helpers

`GeoPlace` SHALL provide `add_relation(to_place, relation_slug)`
(idempotent) and `get_related_places(relation_slug, direction)`
returning a GeoPlace queryset.

#### Scenario: add_relation is idempotent
- **WHEN** `hut.add_relation(zermatt, "part_of")` runs twice
- **THEN** exactly one edge exists

### Requirement: parent field replaced by relations

The `GeoPlace.parent` field SHALL be removed; existing parent links
migrate to `part_of` edges (idempotent data migration; drop +
re-import acceptable per the change's migration plan). No code
references `GeoPlace.parent` afterwards — the cleanup explicitly
covers `providers/base.py`'s `select_related("parent")` (a dead
optimization that would raise `FieldError`) and the `"parent"` entry
in `_track_field_modifications`' simple-fields list. The input schema
drops `parent_id` (an input-contract change, noted in the API
changelog); no output payload ever serialized `parent` — verified.

#### Scenario: Hierarchy preserved
- **WHEN** a place had `parent = municipality`
- **THEN** a `part_of` edge to the municipality exists post-migration

### Requirement: Relation auto-generation during import

The import pipeline SHALL optionally auto-generate relations: spatial
containment → `part_of`, proximity below a configured threshold →
`serves`, with `confidence < 1.0`, idempotent across re-imports
(same triple replaced, curated confidence-1.0 edges preserved), and
bounded to configured place types.

#### Scenario: Containment generates part_of
- **WHEN** an imported place lies within a municipality geometry
- **THEN** a `part_of` edge is created with confidence < 1.0

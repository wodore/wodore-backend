## ADDED Requirements

### Requirement: GeoPlaceRelation stores one-direction semantic edges
The system SHALL provide a `GeoPlaceRelation` model with `from_place` and
`to_place` foreign keys to `GeoPlace` and a `relation` foreign key to
`Category` limited to children of the `relations` category, storing each edge
exactly once (reverse queries swap the FK direction via the
`outgoing_relations` / `incoming_relations` related names).

#### Scenario: Forward and reverse traversal
- **WHEN** a relation `hut -> part_of -> municipality` exists
- **THEN** `hut.outgoing_relations` finds it with `to_place = municipality` and `municipality.incoming_relations` finds it with `from_place = hut`

#### Scenario: Relation choices are constrained
- **WHEN** a GeoPlaceRelation is created with a category whose parent slug is not `relations`
- **THEN** the category is not offered/accepted as a relation type (limit_choices_to on parent slug `relations`)

### Requirement: Relation integrity constraints
GeoPlaceRelation SHALL enforce uniqueness of the `(from_place, to_place, relation)` triple and SHALL reject self-loops (`from_place == to_place`) via database constraints, and SHALL carry a `confidence` score (default 1.0) and an `extra` JSON field for auto-generated edges.

#### Scenario: Duplicate triple rejected
- **WHEN** the same (from, to, relation) triple is inserted twice
- **THEN** the second insert fails with a unique-constraint violation

#### Scenario: Self-loop rejected
- **WHEN** a relation with `from_place == to_place` is inserted
- **THEN** the insert fails with a check-constraint violation

### Requirement: Graph lookup performance indexes
The system SHALL index GeoPlaceRelation on `from_place`, `to_place` and `relation` (composite `(from_place, relation)` and `(to_place, relation)` indexes) so graph traversal does not require spatial operations.

#### Scenario: Indexed traversal
- **WHEN** places related by a given relation slug are queried (`get_related_places("part_of")`)
- **THEN** the database uses the relation indexes and no geometry function is evaluated

### Requirement: GeoPlace helper methods
The `GeoPlace` model SHALL provide `add_relation(to_place, relation_slug, **kwargs)` (idempotent via update_or_create) and `get_related_places(relation_slug=None, direction="outgoing"|"incoming")` returning a GeoPlace queryset.

#### Scenario: add_relation is idempotent
- **WHEN** `hut.add_relation(zermatt, "part_of")` is called twice
- **THEN** exactly one GeoPlaceRelation row exists and it is active

#### Scenario: Direction-aware lookup
- **WHEN** `municipality.get_related_places("part_of", direction="incoming")` is queried
- **THEN** all places whose `part_of` edge points at the municipality are returned

### Requirement: parent field replaced by relations
The system SHALL remove the `GeoPlace.parent` field and SHALL migrate existing parent links into `part_of` GeoPlaceRelations via a `migrate_parent_to_relations` management command before the field removal migration runs.

#### Scenario: Data migration preserves hierarchy
- **WHEN** `migrate_parent_to_relations` runs on data with `place.parent = municipality`
- **THEN** a `part_of` GeoPlaceRelation from place to municipality exists afterwards and the migration is idempotent

#### Scenario: No parent field remains
- **WHEN** the final geometries migration is applied
- **THEN** the GeoPlace model has no `parent` attribute and no code references `GeoPlace.parent`

### Requirement: Relation auto-generation during import
The import pipeline SHALL be able to auto-generate relations: spatial containment produces `part_of`, proximity below a threshold produces `serves`, and OSM operator metadata produces brand classification, storing a `confidence` score below 1.0 for generated edges.

Auto-generation SHALL be idempotent across re-imports (auto-generated edges
with the same triple are replaced, not duplicated; manually curated edges with
confidence 1.0 are preserved) and SHALL be bounded to defined place types
rather than applied to the full GeoNames/OSM corpus.

#### Scenario: Containment generates part_of
- **WHEN** an imported place lies within a municipality geometry
- **THEN** a `part_of` relation to the municipality is created with confidence < 1.0

#### Scenario: Re-import regenerates instead of duplicating
- **WHEN** the import re-runs and the auto-generated `part_of` triple already exists with confidence < 1.0
- **THEN** the edge is updated in place and the total count of auto-generated edges does not grow

#### Scenario: Manual curation survives re-import
- **WHEN** an edge with confidence 1.0 (curated) matches a triple the importer would generate
- **THEN** the curated edge is left unchanged

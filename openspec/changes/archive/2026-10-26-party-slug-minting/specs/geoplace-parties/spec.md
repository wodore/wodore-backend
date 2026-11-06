# Spec Delta: party-slug-minting (geoplace-parties modifications)

## MODIFIED Requirements

### Requirement: Party entity with localized name and links

The system SHALL provide a `Party` entity with a unique short minted
slug (public identifier, `{base}-{random}` per the short-slug-minting
capability), an `extra` JSONB payload (GIN-indexed) carrying the
`osm_name` import identity (normalized name; owner slugs ride the same
key), a localized name, an optional localized note, active/public
flags, a review status, any number of ordered `ExternalLink`
associations (shared link entities with i18n labels, link types, and
health checks), and an optional symbol (two nullable Symbol FKs —
color and mono; the map-styling primitive variant is not used for
parties).

#### Scenario: Party with multiple links
- **WHEN** a party "SAC Bern" is created with a website link and a
  booking link
- **THEN** both links are associated with the party in the given order
  and each carries its own i18n label

#### Scenario: Optional symbol resolves
- **WHEN** a party has symbol FKs set and its symbol URLs are resolved
- **THEN** the color and mono URLs are returned (same helper pattern
  as category symbols); a party without symbols resolves to no
  symbol data

#### Scenario: Slug uniqueness
- **WHEN** a party is saved with a slug that already exists
- **THEN** the save is rejected with a validation error

#### Scenario: Identity rides extra
- **WHEN** an import resolves a party by name and no row carries the
  matching `extra.osm_name` identity yet
- **THEN** an exactly-named existing party is adopted (identity
  stamped) or the party is created with the identity — never a
  same-named duplicate

### Requirement: Admin management of parties

The admin SHALL provide a Party model admin (localized name, links
with ordering) and a GeoPlace inline for party associations (party
autocomplete, role autocomplete scoped to the `role` subtree). Manual
inline edits SHALL mark the place `is_modified` and record
role-scoped protection in `protected_fields` (`{"parties": [...]}`,
the union of changed, added and deleted roles; a legacy flat
`"parties"` entry shields all roles and is kept). Manual external-link
and category inline edits SHALL mark flat `"links"` / `"categories"`
protection. The amenity admin SHALL no longer offer the brand field.

#### Scenario: Editor links a party
- **WHEN** an editor adds party "migros" with role `role.brand` to a
  place in the admin and saves
- **THEN** the association exists, the place is marked modified, and
  only `role.brand` is recorded as protected — an import may still
  add other roles to that place

# Spec Delta: party-slug-minting (geoplace-parties modifications)

## MODIFIED Requirements

### Requirement: Party entity with localized name and links

The system SHALL provide a `Party` entity with a unique short minted
slug (public identifier, `{base}-{random}` per the short-slug-minting
capability), a unique `dedup_key` (normalized name — the import
identity), a localized name, an optional localized note, active/public
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

#### Scenario: Dedup key uniqueness
- **WHEN** two creation paths try to create parties whose normalized
  names collapse to the same dedup key
- **THEN** the second create is rejected by the unique constraint (or
  resolves to the existing row at the get_or_create sites)

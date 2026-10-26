# Spec Delta: party-slug-minting (new capability)

## ADDED Requirements

### Requirement: Generic short-slug minting helper

The system SHALL provide a generic `mint_short_slug(name, *,
fallback, ignore_words, max_length)` helper in `server.core.utils`
that mints a readable public identifier `{base}-{suffix}` without any
database access: the base is derived deterministically from the name
(slugified, `ignore_words` filtered, at most 3 words of >= 3 chars
distributed over a ~9-character target) and falls back to `fallback`
for empty or fully filtered names; the suffix is drawn from
`[a-z0-9]` using a cryptographic random source, sized
`max(5, min(8, max_length - len(base) - 1))`; the result is clamped to
`max_length` (default 15).

#### Scenario: Long name truncates readably
- **WHEN** the helper is called with
  `"Liechtensteinisches Landesspital"` and the geoplace defaults
- **THEN** it returns a slug of at most 15 characters whose base is
  derived from the name's leading words (e.g. `liechland-dne4`)

#### Scenario: Empty name uses the fallback
- **WHEN** the helper is called with an empty name and
  `fallback="place"`
- **THEN** the base is `place` and the slug still carries a random
  suffix (e.g. `place-vn191wad` when space allows)

#### Scenario: Two mints differ
- **WHEN** the helper is called twice with the same name
- **THEN** the two slugs share the base and differ in the random
  suffix

### Requirement: GeoPlace delegates to the helper

`GeoPlace.generate_unique_slug` SHALL delegate to the generic helper
passing the geoplace specifics (amenity ignore words, category-slug
fallback, `"place"` default fallback). Its public signature, outputs,
and documented examples SHALL be unchanged by the refactor.

#### Scenario: Behavior preserved
- **WHEN** the documented example names are minted after the refactor
- **THEN** the outputs match the pre-refactor behavior and the
  existing slug test expectations stay green without modification

### Requirement: Party slugs are minted once with an extras-carried identity

The system SHALL separate a party's import identity from its public
identifier: the identity lives in `Party.extra` JSONB under `osm_name`
(the normalized name — lowercased with whitespace as `_`, truncated to
50 — or the owner slug for merged owners), while `Party.slug` is a
short public identifier minted with the generic helper at creation and
never re-derived. A shared resolver SHALL resolve parties for imports
and the schema write path: identity match first; on miss, a party
whose base `name` matches exactly is adopted by stamping the identity
onto it (manual parties dedupe with imports instead of duplicating);
otherwise the party is created with a minted slug.

#### Scenario: Re-import is idempotent and stable
- **WHEN** the OSM import encounters `brand=Volg` twice across runs
- **THEN** exactly one Party exists for it, matched by the
  `extra.osm_name` identity, and its slug is unchanged between runs

#### Scenario: Name adoption dedupes manual parties
- **WHEN** a name-only write resolves for a party that was created
  manually with the same base name but no identity
- **THEN** the existing party is adopted (identity stamped, slug
  untouched) and no duplicate row is created

#### Scenario: Minted party slug
- **WHEN** a party "SAC Bern" is created without a slug
- **THEN** it is saved with a short minted slug whose base derives
  from the name (e.g. `sac-bern-…`, ≤15 characters) and the identity
  `extra.osm_name = "sac_bern"` written by the creating import path

#### Scenario: Write path resolves by slug or identity
- **WHEN** a `PartyInput` arrives with only a name (no slug) for a
  party that already exists under the name's identity
- **THEN** the existing party is associated (no duplicate row, slug
  untouched); with a slug that matches an existing party, that party
  wins even when the name differs

#### Scenario: Slug uniqueness
- **WHEN** a party is saved with a slug that already exists
- **THEN** the save is rejected with a validation error

### Requirement: Role-scoped party protection

Manual party edits SHALL shield only the roles they touched:
`protected_fields` entries may be structured (`{"parties":
["role.brand", ...]}` — the union of changed, added, and deleted
roles from the admin inline), and the schema update paths SHALL skip
only entries whose role identifier is protected. The legacy flat
`"parties"` string SHALL keep shielding all roles and SHALL never be
silently narrowed.

#### Scenario: Brand protected, operator still written
- **WHEN** a place carries `{"parties": ["role.brand"]}` in its
  protected fields and an import provides a brand and an operator
  party
- **THEN** the operator association is written and the brand entry is
  skipped

#### Scenario: Flat entry shields everything
- **WHEN** a place carries the flat `"parties"` entry and an import
  provides any party entries
- **THEN** none are written

### Requirement: Links and categories shielded on manual edits

Manual external-link and category inline edits SHALL mark the place
`is_modified` and record flat `"links"` / `"categories"` entries in
`protected_fields`; the OSM import SHALL NOT add external links to a
`"links"`-protected place.

#### Scenario: Protected place receives no import links
- **WHEN** the OSM import processes a place whose protected fields
  contain `"links"`
- **THEN** no external link is added or created for it

#### Scenario: Manual link edit marks protection
- **WHEN** an editor changes the external-link inline of a place and
  saves
- **THEN** the place is marked modified and `"links"` is recorded in
  its protected fields

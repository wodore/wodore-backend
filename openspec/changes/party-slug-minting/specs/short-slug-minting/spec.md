# Spec Delta: party-slug-minting (new capability)

## ADDED Requirements

### Requirement: Generic short-slug minting helper

The system SHALL provide a generic `mint_short_slug(name, *,
fallback, ignore_words, max_length)` helper in `server.core.utils`
that mints a readable public identifier `{base}-{suffix}` without any
database access: the base is derived deterministically from the name
(slugified, `ignore_words` filtered, at most 3 words distributed over
a ~9-character target, minimum 3 characters per word) and falls back
to `fallback` for empty or fully filtered names; the suffix is drawn
from `[a-z0-9]` using a cryptographic random source, sized
`max(5, min(8, max_length - len(base) - 1))`; the result is clamped to
`max_length` (default 15).

#### Scenario: Long name truncates readably
- **WHEN** the helper is called with
  `"Liechtensteinisches Landesspital"` and the geoplace defaults
- **THEN** it returns a slug of at most 15 characters whose base is
  derived from the name's leading words (e.g. `liechtenst-dne4`)

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
- **THEN** the outputs match the documented examples' shape and the
  pre-refactor test expectations stay green without modification

### Requirement: Party slugs are minted once and deduped by key

The system SHALL separate a party's import identity from its public
identifier: `Party.dedup_key` (unique, the normalized name — lowercased
with whitespace as `_`, truncated to 50 — or the owner slug for
merged owners) resolves re-imports and write-path lookups, while
`Party.slug` is a short public identifier minted with the generic
helper at creation and never re-derived. Party creation paths (model
save with a blank slug, schema write path, imports) SHALL mint; all
`get_or_create` dedup sites SHALL key on `dedup_key`.

#### Scenario: Re-import is idempotent and stable
- **WHEN** the OSM import encounters `brand=Volg` twice across runs
- **THEN** exactly one Party exists for it, matched by dedup key, and
  its slug is unchanged between the runs

#### Scenario: Minted party slug
- **WHEN** a party "SAC Bern" is created without a slug
- **THEN** it is saved with a short minted slug whose base derives
  from the name (e.g. `sac-bern-…`, ≤15 characters) and a dedup key
  `sac_bern`

#### Scenario: Write path resolves by slug or key
- **WHEN** a `PartyInput` arrives with only a name (no slug) for a
  party that already exists under the name's dedup key
- **THEN** the existing party is associated (no duplicate row, slug
  untouched); with a slug that matches an existing party, that party
  wins even when the name differs

#### Scenario: Slug uniqueness
- **WHEN** a party is saved with a slug that already exists
- **THEN** the save is rejected with a validation error

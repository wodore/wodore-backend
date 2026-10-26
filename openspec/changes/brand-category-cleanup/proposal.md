# Proposal: brand-category-cleanup

## Why

The `geoplace-parties` change (#415) moved brands from categories to
parties, but its conversion migration (geometries 0053) deliberately
left the `root.brand` category subtree in the database for rollback
safety. That migration has shipped; nothing in the codebase references
the subtree anymore (the OSM import now mints parties, the brand FK and
`_get_or_create_brand_category` are gone) — the leftover vocabulary is
dead data cluttering the category admin and the tree.

## What Changes

- Data migration removing the legacy `root.brand` category subtree:
  - delete `GeoPlaceCategory` association rows that point at
    `root.brand` children first (the category FK is RESTRICT; those
    associations are superseded by `role.brand` party associations
    written by 0053),
  - then delete the `root.brand` parent (children cascade).
- Idempotent (vocabulary already absent → no-op) with a no-op reverse:
  the brand categories were import-minted and are not re-derivable, but
  the rollback-safety window has passed — the Party rows carry the
  names.
- Spec delta updating the `geoplace-parties` main spec: the
  "shall remain until a later cleanup" clause is fulfilled.

## Capabilities

### New Capabilities

- none

### Modified Capabilities

- `geoplace-parties`: the *Brand category replacement* requirement now
  ends with the subtree actually being removed (cleanup migration).

## Impact

- Database only (one data migration, no schema change, no code path
  changes). Category admin loses the dead `brand.*` entries — intended.
- Covered by migration dry-runs on the lane DB plus a unit test that
  seeds the legacy vocabulary and asserts it is gone (and that
  non-brand categories survive).

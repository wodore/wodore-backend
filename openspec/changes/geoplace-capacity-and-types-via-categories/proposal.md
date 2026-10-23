# Proposal: geoplace-capacity-and-types-via-categories

## Why

The Hut → GeoPlace migration is blocked on two pieces of hut data that have
no home on `GeoPlace`: bed capacity (`capacity_open`/`capacity_closed`) and
the closed-season type (`hut_type_closed`). The multi-category rework
(WEP008, `_work/260311_geoplace_multi_categories.md`) already added the
flexible mechanism for exactly this — `GeoPlaceCategory.classifier` (a
Category FK "e.g. seasonal status") and `GeoPlaceCategory.extra`
("category-specific overflow data") — but its semantics were deliberately
left undefined ("needed later"): today 0 of 458,904 associations use
`classifier` or `extra`, and no `season.*` categories exist. Defining these
semantics now unblocks the hut migration without inventing an
`AccommodationDetail` model and keeps attributes category-driven and
extensible for any source.

## What Changes

- Define the semantics of the association-level fields on
  `GeoPlaceCategory`:
  - `classifier`: a category under a dedicated `season` parent,
    qualifying *how* the place operates in the closed season (e.g.
    `season.winter_room`, `season.self_service`, `season.closed`).
  - `extra`: typed per-association attributes — `capacity_open` and
    `capacity_closed` (ints, optional) for accommodation associations.
- Create the `season` category vocabulary (parent + children) derived from
  the existing `hut_type_closed` values (`selfhut` → `season.self_service`,
  `bivouac` → `season.winter_room`, `closed` → `season.closed`, unstaffed
  year-round → `season.year_round`, unknown → no classifier).
- Rewrite the wodore hut import (`import_geoplaces -s wodore`) onto the
  schema path (`GeoPlace.update_or_create`) and populate: category from
  `hut_type_open`, classifier from `hut_type_closed`, `extra` capacities,
  plus the already-mapped base fields (name, location, elevation, country,
  flags, description).
- Expose `classifier` and `extra` in the GeoPlace API category payloads
  (search/nearby/amenity detail — selected via the `fields[places]` sparse
  fieldset). Tiles already pass `gpc.extra` through `geoplaces_for_tiles`;
  the view additionally gains the `classifier` identifier.
- Make `classifier` and `extra` editable in `GeoPlaceCategoryInline`
  (admin), with `extra` rendered as a per-key labeled field for the known
  capacity keys.
- Validation: capacities must be `null` or non-negative ints; `classifier`
  must reference a category whose parent is `season`; association stays
  unique per `(geo_place, category)` (existing constraint).

No new detail model: `AmenityDetail` continues to carry phones/opening
hours; capacity and seasonality live on the association, where sources with
conflicting values can be merged per WEP008's priority/protected-fields
policy.

## Capabilities

### New Capabilities

- `geoplace-category-attributes`: Requirements for per-association
  attributes on GeoPlace categories — season classification via
  `classifier`, typed capacities via `extra`, validation rules, write paths
  (wodore hut import, admin), and read paths (API category payloads,
  martin tile view).

### Modified Capabilities

(none — no existing spec in `openspec/specs/` covers category associations
or the geoplace API surface this touches. The API addition is additive and
follows `api-conventions`: it is registered as an entry in the API
changelog during implementation, per the `api-changelog` capability.)

## Impact

- **Models**: `server/apps/geometries/models/_associations.py`
  (GeoPlaceCategory — help texts/validators only, no schema migration
  needed beyond the `season` category data); `server/apps/categories`
  (fixture/migration for the `season` subtree).
- **Import**: `server/apps/geometries/management/commands/import_geoplaces.py`
  (wodore handler rewrite onto `update_or_create`).
- **API**: `server/apps/geometries/schemas/_output.py`,
  `server/apps/geometries/api.py` (category payload extension under the
  `fields[places]` sparse-fieldset selection); API changelog entry per
  `api-conventions`.
- **Admin**: `server/apps/geometries/admin/_geoplace.py`
  (`GeoPlaceCategoryInline` — already renders `classifier`; gains
  season-scoped autocomplete, `extra` capacity fields, and modification
  tracking).
- **Tiles**: `server/apps/geometries/models/tiles_view.py`
  (`geoplaces_for_tiles` view — add `classifier` next to the existing
  `extra`).
- **Tests**: factories + import/API/admin tests for the new attributes.
- **Non-goals**: migrating availability/booking off `Hut` (separate change;
  a follow-up proposal `geoplace-availability` will cover re-anchoring
  availability — including how `HutAvailability`/`HutAvailabilityHistory`
  are preserved — and the eventual `Hut` removal); populating
  `AmenityDetail` for huts (phones, `open_monthly` → `opening_months`,
  `url`/contact URLs → external links, `hut_owner` → owner/brand mapping —
  separate change); `Note` model (WEP008, deferred); OSM accommodation
  imports.

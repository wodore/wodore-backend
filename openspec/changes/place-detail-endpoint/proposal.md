# Proposal: place-detail-endpoint

## Why

The public geo API has exactly one per-place detail route —
`GET /v1/geo/places/amenity/{place_id}` — hardcoded to
`detail_type="amenity"`. GeoPlace has five detail types (amenity,
transport, admin, natural, none), `AdminDetail` exists with no endpoint,
and transport/natural have neither model nor route. A per-type URL space
would multiply endpoints as detail blocks arrive, while the large
majority of places (every peak, pass, lake and village) have no detail
route at all.

The geo surface is pre-release (owner: "geoplaces are not live and we
can change as much as we want"; the amenity endpoint shipped four latent
crash bugs with zero test coverage and no call sites), so this is the
cheap moment to also fix its identifier story: owner decision — the
places family goes **slug-only**. Slugs are de facto mandatory (0 NULL
in 441,940 rows, minted once at creation, never rewritten), every
user-facing surface is already slug-keyed, and api-conventions demands
slugs without PKs. The numeric `id` leaves the responses, and the item
route keys by slug.

## What Changes

- Add `GET /v1/geo/places/{slug}` — one unified detail endpoint for
  **every** active, public GeoPlace regardless of `detail_type`. The
  type is a response field, not a path segment.
- **Slug-only identifiers family-wide**: `search`, `nearby` and the
  detail route carry `slug` and no numeric `id` (breaking; see below).
- Response: base fields (`slug`, localized `name`, `country_code`,
  `elevation`, `importance`, `location`, `description`,
  `review_status`, `detail_type`) plus optional members `categories`,
  `sources`, `amenity`, `parties` (per `geoplace-parties`) under
  the existing `fields[places]` sparse-fieldset selection.
- **Routing that works in any case**: a registered slug path converter
  whose grammar (slug chars with at least one `-` or `_` — true for
  441,940/441,940 rows by construction) structurally cannot match the
  fixed collection segments (`search`, `nearby`, `overlays`); item
  routing becomes order-independent. Model-layer validation makes the
  grammar a data invariant; the SEO siblings (`{slug}/meta`,
  `{slug}.md`) adopt the same converter.
- `amenity` is the first detail block; admin/transport/natural
  follow later as sibling optional members (extension pattern fixed
  here, blocks not).
- **`places/amenity/{place_id}` is removed** (no alias — pre-release,
  zero consumers) in the same breaking version.
- Breaking changes are amended into the current *unreleased* API
  version per the runbook (no client ever received it; precedent: the
  2026-10-02 no-consumer removal with sunset window 0).
- Drop the vestigial `null=True` on `GeoPlace.slug` (de jure NOT NULL).

## Capabilities

### New Capabilities

- `place-detail-api`: the unified slug-keyed place detail endpoint —
  slug-only identifiers across the places family, the slug path
  grammar/converter and routing-safety rules, response shape and
  sparse-fieldset selection incl. the detail-block extension pattern,
  the amenity route removal and breaking-version lifecycle, the slug
  invariant, caching parity, and the 404 contract.

## Impact

- `server/apps/geometries/api.py` — new `get_place` controller + route;
  `get_amenity` route and controller removed; SEO paths adopt the
  converter
- `server/apps/api/` (or geometries) — `GeoPlaceSlugConverter`,
  registered for `<geoplace:slug>`
- `server/apps/geometries/presenters.py`, `schemas/_output.py` —
  slug-for-id swap, `GeoPlaceDetailSchema`
- `server/apps/geometries/models/_geoplace.py` + migrations — slug
  `null=False`, grammar/reserved-name validation
- `server/apps/apiversions/registry.py` — amend the unreleased
  `VersionChange`; snapshot regenerated
- Frontend: regenerate the API client (geo operations change shape;
  no call sites exist for the removed route)
- Composes with pending `geoplace-parties` (parties member, projection
  fix) — dependency assumption, not duplicated
- No hut endpoints; the huts family is untouched

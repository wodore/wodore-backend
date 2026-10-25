# Proposal: place-detail-endpoint

## Why

The public geo API has exactly one per-place detail route —
`GET /v1/geo/places/amenity/{place_id}` — hardcoded to
`detail_type="amenity"`. GeoPlace has five detail types (amenity,
transport, admin, natural, none), `AdminDetail` exists with no endpoint,
and transport/natural have neither model nor route. A per-type URL space
would multiply endpoints as detail blocks arrive, while the large
majority of places (every peak, pass, lake and village — no amenity
detail) have no detail route at all: the frontend cannot build a place
page from search/map context for them.

Evidence the surface is greenfield: the amenity endpoint shipped with
four latent crash bugs and zero test coverage (fixed in the pending
`geoplace-parties` change) — no working consumer exists; the generated
frontend client declares it but has no call sites. Unifying now is
cheap; unifying after consumers bind to per-type URLs is not.

## What Changes

- Add `GET /v1/geo/places/{place_id}` — one unified detail endpoint for
  **every** active, public GeoPlace regardless of `detail_type`. The
  type is a response field (`detail_type`), not a path segment.
- Response: base place fields (`id`, `slug`, localized `name`,
  `country_code`, `elevation`, `importance`, `location`, `description`,
  `review_status`, `detail_type`) plus optional members `categories`,
  `sources`, `amenity_detail`, `parties` (per `geoplace-parties`) under
  the existing `fields[places]` sparse-fieldset selection.
- Path keyed by the stable numeric GeoPlace id (int path converter),
  resolving the open id-vs-slug design point (reasoned decision in
  design.md D1); the response carries `slug` so clients can build
  `place/{slug}` frontend URLs.
- `amenity_detail` is the first detail block; admin/transport/natural
  follow later as sibling optional members (one additive change each —
  the extension pattern is fixed here, the blocks are not).
- The old `places/amenity/{place_id}` route stays as a deprecated alias
  delegating to the unified implementation (amenity-scoped 404
  semantics preserved); retiring it later is an `api:breaking` version
  bump per `docs/api-versioning.md`.
- Amend `api-conventions`' slug-identifier requirement with a
  family-consistency clause (the geo places family is id-keyed).
- Drop the vestigial `null=True` on `GeoPlace.slug`: the field has
  been de facto mandatory since its introducing migration backfilled
  every row — now enforced NOT NULL (D8; `blank=True` stays, `save()`
  mints).

Additive only — new endpoint, new optional response members — no API
contract version bump.

## Capabilities

### New Capabilities

- `place-detail-api`: the unified place detail endpoint — path keying
  and resolution rules, response shape, sparse-fieldset selection of
  optional members incl. the detail-block extension pattern, the
  deprecated amenity alias and its retirement lifecycle, caching
  parity, and the 404 contract.

### Modified Capabilities

- `api-conventions`: the "Slug identifiers and ISO modified timestamps"
  requirement gains an id-keyed-family carve-out — new endpoints in an
  id-keyed family follow the family's identifier convention instead of
  introducing a parallel slug key.

## Impact

- `server/apps/geometries/api.py` — new `get_place` controller + route;
  `AmenityController` becomes a thin deprecated alias
- `server/apps/geometries/presenters.py` — shared detail presenter
  (reuses `base_result`, `build_categories_data`, `annotate_sources`,
  `build_sources`)
- `server/apps/geometries/schemas/_output.py` — `GeoPlaceDetailSchema`
- `server/apps/geometries/models/_geoplace.py` + migration — slug
  `null=False` cleanup
- tests for the endpoint/alias contract; OpenAPI snapshot regeneration
- Composes with pending `geoplace-parties` (parties member, nested
  projection fix) — dependency assumption, not duplicated here
- No hut endpoints, no huts app changes; no DB migrations

# Design: place-detail-endpoint

## Context

Current surface under `/v1/geo/` (dmr controllers in
`server/apps/geometries/api.py`):

- `places/search`, `places/nearby` — list endpoints. Responses carry
  `id` (no `slug` member anywhere in `GeoPlaceBaseSchema`) with
  optional `categories`/`sources` members under `fields[places]`
  selection (`field_selected` gating skips DB work).
- `places/overlays` — category registry.
- `places/amenity/<int:place_id>` (`get_amenity`) — the ONLY detail
  endpoint: filters `detail_type="amenity"` (404 for anything else),
  `is_active=True` but **not** `is_public` (inconsistent with search
  and the SEO surface). Returns `AmenitySchema`; accepts `lang` and
  `fields[TYPE]` but does not narrow the response.
- Content surfaces are slug-keyed: `places/<str:slug>/meta` and
  `places/<str:slug>.md` (`api_seo.py`), images at `place/<str:slug>`
  (`api_images.py`); the frontend's place pages use
  `PLACE_URL_PATTERN = place/{slug}`.

So machine surface = int id, content/URL surface = slug — the
inconsistency this change must resolve for the unified detail endpoint.

GeoPlace facts that drive the keying decision:

- `id`: bigint PK — stable across OSM re-imports, dedupe merges and
  renames; never re-minted, never moves between rows.
- `slug`: `SlugField(max_length=15, unique, db_index, null=True)` —
  "temporarily nullable for migration"; auto-minted on first save from
  the English name (`slugify`), truncated to 15 chars, UUID-suffixed on
  collision (`generate_unique_slug`); **not returned by any geo list or
  detail response today**. Merges/re-imports can re-mint or orphan
  slugs (a dedupe merge makes the losing row's slug vanish → deep
  links rot); ids never move.

Routing constraint: the `places/` namespace has fixed siblings
(`search`, `nearby`, `overlays`). A `<str:key>` converter at
`places/{key}` matches them (resolution becomes order-dependent; a
place whose slug is literally `search` becomes unreachable). An `<int:
place_id>` converter cannot match any of them — zero collision, no
ordering games.

Dependency assumption: the pending `geoplace-parties` change adds the
`parties` member on GeoPlace responses under `fields[places]` (nested
`fields[parties]` narrowing), the nested projection required-fields
fix, and the Party/role machinery. This change composes with it and
does not re-specify it. Landing order is flexible (see Migration Plan).

House-standard tension: the `api-conventions` capability requires slug
identifiers and no PK exposure for new endpoints — but its Purpose
grandfathers existing shapes "until meaningfully modified", and the
entire geo places family (search/nearby/amenity) is id-keyed and
exposes `id` in every payload. Decision 6 resolves this in the specs,
not just in this doc.

## Goals / Non-Goals

Goals:

- One detail endpoint that serves every place regardless of
  `detail_type` — places without a detail block are first-class.
- Detail blocks and shared members (`categories`, `sources`, `parties`)
  optional via the existing `fields[places]` selection, with DB-cost
  gating parity.
- A reasoned, recorded id-vs-slug path-keying decision with explicit
  resolution rules.
- Alias + deprecation lifecycle for the amenity path per
  `docs/api-versioning.md`.

Non-Goals:

- No hut endpoints, no huts app changes (owner constraint: geometries
  only, general).
- No `admin_detail`/`transport_detail`/`natural_detail` blocks here —
  later changes; only the extension pattern is fixed.
- No type/category filter parameters on the detail route (the place IS
  its type; filtering belongs to `search`/`nearby`).
- No slug-quality workstream (longer slugs, immutability guarantees,
  slug in list responses).
- No ETag machinery (hut-style ETags may come later; the family tier is
  time-based today).

## Decisions

1. **Path keying: numeric id — `GET /v1/geo/places/{place_id}`, int
   path converter.** The owner-flagged open point, resolved against
   three options:

   | Criterion | A: id-only | B: slug-only | C: dual id-or-slug |
   |---|---|---|---|
   | List→detail navigation | native (search/nearby return `id`) | blocked — lists return no slug; requires a prerequisite change exposing it everywhere | works for id callers; slug callers still need exposure |
   | Identifier stability | immune to import churn | exposed to 15-char truncation, UUID suffixes, re-minting on merge/dedupe (deep links rot) | same exposure for the slug half |
   | Routing | zero collision (`<int>` can't match `search`/`nearby`/`overlays`) | `<str:key>` collides with fixed siblings → needs `by-slug/` prefix or fragile ordering | same collision |
   | Ambiguity | none | none | numeric-slug hazard: `slugify("88")` → `"88"` — a place named with digits is indistinguishable from an id; precedence rules silently change meaning as data grows |
   | Cache/404 semantics | one key namespace | one | two key namespaces per resource; 404 debugging muddied (miss-by-id vs miss-by-slug) |
   | URL friendliness | poor | best | mixed |
   | api-conventions | deviates (family-consistent) | compliant | deviates |
   | Versioning cost later | alias retirement is the only breaking step | migrating lists to slug = family-wide breaking | retiring either half = breaking |

   **Recommendation: A.** The convention's own precondition — "stable,
   human-readable slugs" — is not met by `GeoPlace.slug` as it exists
   (auto-minted, truncated, UUID-suffixed, nullable), and the geo
   family is id-keyed end to end and grandfathered as such. A slug-
   keyed detail endpoint would be unaddressable from the list results
   clients actually consume, and dual-key pays permanent ambiguity and
   double cache/404 namespaces for a bridge nobody needs (zero
   consumers today; the slug audience — frontend URLs, edge meta,
   LLMs — is already served by the slug-keyed SEO/images surfaces).

   Mitigations: the response carries `slug` when set, so clients build
   `place/{slug}` URLs from a detail fetch; the convention deviation is
   recorded in the specs (D6); the revisit trigger is explicit — a
   concrete consumer needing slug→full-detail deep links plus a slug-
   quality workstream, at which point slug addressing can be added
   additively (e.g. `places/by-slug/{slug}`).

2. **One implementation, amenity-scoped alias delegates.** New
   `PlaceController` (`get_place`, URL name `get_place`) at
   `places/<int:place_id>`. `AmenityController` keeps its identity
   (`get_amenity`) and becomes a thin alias delegating to the same
   shared presenter, adding the `detail_type="amenity"` scope so its
   observable 404-for-non-amenity semantics are preserved exactly (a
   natural place 404s on the alias, 200s on the unified route). The
   alias response is the unified body — a strict superset of today's
   `AmenitySchema` (adds `slug`; `parties` per `geoplace-parties`) —
   hence additive. Accepted alias delta: resolution adds
   `is_public=True` (today the amenity route can serve non-public
   places — a bug against search/SEO parity; zero consumers, bugfix
   grade). Both routes keep the visit-counting hook
   (`place-visit-counter` unchanged — counting happens once per
   successful detail fetch).

3. **Response shape and projection.** `GeoPlaceDetailSchema`
   (`GeoPlaceBaseSchema` + `description`, `review_status`,
   `detail_type`, `amenity_detail`, `slug`, and `parties` per the
   parties change). Required members: `id`, `name`, `detail_type` (the
   discriminator clients switch on), `location`, `importance` —
   mirroring the base schema's required set. Optional members follow
   the `fields[places]` selection exactly like `nearby` (dict-level
   `project_fields` narrowing; required members and i18n companions
   kept — assumes the `geoplace-parties` projection fix). Without a
   selection: the full response, every member that has data. With a
   selection: only selected + required members. `field_selected`
   gating skips `select_related`/`prefetch_related`/annotations for
   unselected members (search/nearby pattern). A detail block is
   present iff `detail_type` matches, the detail row exists, and the
   member is not deselected — never fabricated for other types and
   never a 400. Not-yet-existing block names (`admin_detail`, …)
   400 as unknown field names naming the valid values — correct
   allowlist behavior, and each future block change adds its name
   additively.

4. **Visibility and the 404 contract.** Resolution filters
   `is_active=True, is_public=True` — parity with search and the SEO
   surface. Unknown, inactive or non-public ids answer 404 via
   `raise_not_found(...)` — the single error contract
   (`api-conventions`): `{"code": "not_found", "detail": …}` plus the
   RFC 9457 members (`type`, `title`, `status`, `instance`), with no
   distinction between "does not exist" and "not public" (no existence
   oracle).

5. **Caching parity.** `@modify(headers=cache_headers(60))` plus
   server-side `cache_page(60)` on both routes — the places-family
   tier (search/nearby/amenity/overlays all 60; the SEO surface's
   3600 tier stays where it is). The evolving-document ETag tier does
   not apply to detail views today. `cache_page` keys on the full URL,
   so `lang` and `fields` variants cache as distinct entries for free.

6. **api-conventions amendment — id-keyed-family carve-out.** The
   spec delta MODIFIES "Slug identifiers and ISO modified timestamps":
   new endpoints in a resource family that is id-keyed end to end (the
   geo places family) follow the family's identifier convention —
   integer path key, `id` in payloads — instead of introducing a
   parallel slug key; a family migrates to slugs, if ever, as one
   coordinated breaking change. Recorded in the specs so the set stays
   self-consistent instead of silently contradicting the new endpoint.

7. **Extension pattern for future detail blocks.** One optional
   sibling member per detail model (`admin_detail`,
   `transport_detail`, `natural_detail`), each gated on `detail_type`
   match + row existence + field selection, added additively in its
   own change. Deliberately no wrapper object (`"details": {...}`):
   sparse fieldsets select flat members, and per-type blocks arrive
   independently — a wrapper would couple their releases and break the
   one-nesting-level projection model.

## Risks / Trade-offs

- **Deviating from the slug-identifier convention** — mitigated by the
  MODIFIED requirement recording the family rule (D6) and the explicit
  revisit trigger (D1). The alternative (slug here, id everywhere
  else) strands the endpoint from its own list results.
- **Alias tightening (`is_public`)** — behavior delta on an existing
  route, but bugfix-grade (serving non-public places publicly), with
  evidence of zero consumers; flagged in the PR description for the
  `api:added` label review.
- **60s `cache_page` staleness** — same exposure as the family; detail
  edits propagate within a minute. If editors ever need instant
  visibility, the evolving-document ETag tier is the documented path.
- **`fields[places]=admin_detail` 400s today** — correct allowlist
  behavior (the error names the valid values); each future block
  change widens it additively.

## Migration Plan

None — no DB or schema changes. Sequencing: land after (or together
with) `geoplace-parties` so the `parties` member and the projection fix
are in place; landing before is also valid — the parties change already
requires the member on GeoPlace responses and would add it to the
detail route when it lands.

## Open Questions

None. Path keying is resolved (D1: id, with slug as a response field).
The rollout order of later blocks (admin is the natural next — its
model exists) is a per-change decision outside this spec.

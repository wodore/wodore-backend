# Design: place-detail-endpoint

## Context

Current surface under `/v1/geo/` (dmr controllers in
`server/apps/geometries/api.py`, mounted via `Router("geo/", …)` —
most-specific-prefix-first, see `api_v1.py`):

- `places/search`, `places/nearby` — list endpoints; responses carry
  numeric `id`, no slug member; optional `categories`/`sources` under
  `fields[places]`.
- `places/overlays` — category registry (fixed segment).
- `places/amenity/<int:place_id>` (`get_amenity`) — the only detail
  endpoint, amenity-scoped, `is_active` but not `is_public`.
- `places/<str:slug>/meta` + `places/<str:slug>.md` (SEO/LLM,
  slug-keyed) — item paths at the same position as the fixed segments,
  using Django's permissive default `str` converter.
- `geo/images/nearby` (fixed) + `geo/images/place/<str:place_slug>` +
`geo/images/hut/<str:hut_slug>` — items namespaced under fixed
prefixes (the existing collision-avoidance precedent).

Identifier facts (verified against migrations and the dev-snapshot
lane DB):

- `id`: plain `AutoField` → int4; no UUID anywhere.
- `slug`: born `null=True` in migration 0012 (2026-03-09, PR #103)
  whose own backfill populated every row — **441,940/441,940 non-null,
  0 NULL**; minted exactly once at creation (`{base}-{5-8 random
  chars}`, e.g. `bern-26xo40q9`) and never rewritten (all `.slug =`
  assignments are creation paths); **0 purely-numeric and 0 pure-word
  slugs** — every slug contains at least one `-` or `_`. Legacy shapes
  exist and stay: 20% have short suffixes or underscore bases
  (`information-5h9`, `vending_machine`), 8,260 have a trailing hyphen
  (`drinking_water-`).
- Owner decision (this change): the places family goes **slug-only** —
  slug in every response, no numeric id, item routes keyed by slug.
  Geoplaces are pre-release, so the family can break its old contract
  freely.
- Version registry: one *unreleased* current version (the
  sparse-fieldsets harmonization, already touching `get_amenity`) —
  the runbook requires amending breaking changes into it, never
  stacking. Precedent for no-consumer removals: 2026-10-02
  (`include`/`exclude` removed, sunset window 0).
- Dependency assumption: pending `geoplace-parties` adds the
  `parties` member under `fields[places]` and the nested projection
  fix; this change composes with it, landing order flexible.

## Goals / Non-Goals

Goals:

- One detail endpoint that serves every place regardless of
  `detail_type` — places without a detail block are first-class.
- Slug-only identifiers in the places family; routing that is
  structurally safe (order-independent, collision-proof by grammar).
- Detail blocks and shared members optional via `fields[places]`,
  with DB-cost gating parity.
- A clean breaking transition: amended into the unreleased version,
  amenity route removed, snapshot regenerated.

Non-Goals:

- No hut endpoints, no huts app changes (owner constraint).
- No `admin`/`transport`/`natural` blocks here.
- No type/category filter parameters on the detail route.
- No slug normalization of legacy shapes (`information-5h9`,
  `vending_machine`, `drinking_water-` stay — they satisfy the
  grammar; churn buys nothing pre-release).
- No ETag machinery (family tier is time-based today).

## Decisions

1. **Slug-only identifiers (owner decision, supersedes the earlier
   id-keyed recommendation).** Every places-family response —
   `search`, `nearby`, the new detail route — carries `slug` as the
   required identifier member and no numeric `id`. The blockers that
   argued for id are each resolved: navigation (lists now return the
   key clients need — slug), family consistency (the whole family
   migrates in one pre-release stroke instead of a new endpoint
   diverging from its lists), api-conventions (now compliant — no
   carve-out delta needed), and routing (D2). The earlier "slug is
   opaque" observation stands but stops mattering: the value of the
   slug is URL stability and one identifier across user-facing pages,
   SEO surface and API — not readability. PKs stay internal.

2. **Routing safety by grammar, not by ordering — the registered
   `GeoPlaceSlugConverter`.** The current path creation is fragile:
   item-shaped routes use Django's default `str` converter, which
   matches any non-slash segment, so coexisting item and fixed routes
   (`places/{slug}` vs `places/search`) can only be told apart by
   list order, and a place whose slug equals a fixed segment would be
   unreachable. The fix makes the two grammars provably disjoint:

   - Converter grammar: `[a-z0-9_-]*[-_][a-z0-9_-]*` — slug charset
     (lowercase, digits, hyphen, underscore) containing at least one
     `-` or `_`. Verified: all 441,940 production slugs match; the
     grammar tolerates the legacy shapes (underscore bases, trailing
     hyphens).
   - Fixed-segment rule: fixed collection segments under `places/`
     (`search`, `nearby`, `overlays`) are single lowercase words —
     they contain neither `-` nor `_` and thus can *never* match the
     converter. URL resolution becomes order-independent: "routing
     works in any case".
   - Registered via `django.urls.register_converter`, used as
     `places/<geoplace:slug>` (dmr's `path()` passes route strings
     through to Django). The SEO siblings adopt it too
     (`places/<geoplace:slug>/meta`, `places/<geoplace:slug>.md`) —
     the `.md`/`/meta` suffixes and the dot-free grammar keep those
     disjoint from the item route.
   - Database-level enforcement makes the grammar a data invariant:
     a `CheckConstraint` on the slug column matching the converter
     regex (`^[a-z0-9_-]*[-_][a-z0-9_-]*$`, sibling of the existing
     `detail_type_valid`/`review_status_valid` constraints) covers
     every write path — Django `save()` does not run `clean()`, so a
     validator alone would be advisory only. `GeoPlace.clean()`/
     `clean_slug` mirrors the constraint plus a reserved-name
     blacklist (`search`, `nearby`, `overlays`, `meta`, `amenity`)
     for friendly admin errors; mint paths already comply (the
     generator always emits `{base}-{suffix}`), so this only
     constrains manual edits. Verified: 0 of 441,940 production
     slugs violate the regex — the constraint applies with no data
     changes.
   - Alternatives rejected: namespacing items under a fixed prefix
     (`places/detail/{slug}` — the images precedent) because it
     breaks URL parity with the existing slug-keyed SEO surface;
     `places/by_slug/{slug}` — in industry usage that shape marks a
     *secondary/alternate-key* lookup (Microsoft Graph's
     alternate-key pattern, `users/by-email/{email}` style), i.e. it
     signals "the canonical key is something else"; ours is the
     primary key, so it would mislead clients and add permanent
     noise while solving nothing the grammar doesn't; a singular
     `place/{slug}` — splits one resource across two nouns
     (`places/search` vs `place/{slug}`) against the plural-collection
     convention (Google AIP-122 resource names, Zalando "MUST
     pluralize", Microsoft guidelines; singular is for singletons/
     controllers like `/me`, `/search`) — the images API's `place/`
     prefix is a collision workaround, not a pattern to spread;
     moving the query endpoints up (`geo/search`, `geo/nearby`) to
     leave `places/` a pure collection — the REST purist's answer and
     the only alternative with a real design argument, but it breaks
     two live endpoints for churn where the grammar achieves the same
     guarantee additively; relying on path-list ordering (the
     fragility being fixed); normalizing legacy slugs (churn, no
     consumer). The chosen shape is the industry standard carried to
     its conclusion: Stripe serves `/v1/customers/search` and
     `/v1/customers/{cus_X}` on the same collection, disambiguated
     purely by the id grammar (`cus_` prefixes) — our slug grammar is
     the same mechanism; Google AIP-122's resource names are exactly
     `collection/{id}`; and the repo's own hut family already serves
     `huts/{slug}` item-on-collection.

3. **Unified endpoint shape.** `GET /v1/geo/places/{slug}`
   (`get_place`, URL name `get_place`) returns the bare place object:
   required members `slug`, `name`, `detail_type` (the discriminator),
   `location`, `importance`; optional members `country_code`,
   `elevation`, `description`, `review_status`, `categories`,
   `sources`, `amenity`, `parties` (per `geoplace-parties`).
   Optional members follow the `fields[places]` selection exactly
   like `nearby` (dict-level `project_fields`; required members and
   i18n companions kept — assumes the parties-change projection fix).
   Without a selection: everything present. `field_selected` gating
   skips DB work for unselected members. A detail block is present
   iff `detail_type` matches, the row exists, and the member is not
   deselected — never fabricated, never a 400 for another type's
   block; not-yet-existing block names 400 as unknown field names
   naming valid values (each future block adds its name additively).

4. **Breaking transition: amend the unreleased version, remove
   `get_amenity`.** Removing `id` from search/nearby/amenity and
   deleting the amenity route are breaking per the runbook, but the
   registry has exactly one *unreleased* version — the runbook
   mandates amending it (a version no client ever received must not
   become its own contract boundary) and CI rejects stacking. Follow
   the 2026-10-02 precedent for no-consumer removals: document the
   removal in the `VersionChange` description (sunset window 0, zero
   consumers — the frontend client declares `get_amenity` but has no
   call sites; the four latent crash bugs prove no working consumer).
   No alias: a deprecated alias would preserve the id-keyed contract
   this change exists to retire, for an audience of zero. Steps:
   extend the unreleased `VersionChange` (description; no downgrade
   transforms needed for removals with sunset window 0), regenerate
   and commit the snapshot, label `api:breaking` + `type:feature`,
   regenerate the frontend client.

5. **Visibility, 404, caching, visits.** Resolution filters
   `is_active=True, is_public=True` (search/SEO parity). Unknown,
   inactive or non-public slugs answer 404 via `raise_not_found` —
   the single error contract (`{"code": "not_found", …}` + RFC 9457
   members, `instance` included), no existence oracle. Both cache
   tiers stay family-parity: `Cache-Control: public, max-age=60` +
   `cache_page(60)`; `cache_page` keys on the full URL so `lang`/
   `fields` variants cache separately. `record_visit` after
   existence is known (`place-visit-counter` unchanged).

6. **Slug invariant (de jure).** `AlterField` to `null=False`
   (0 NULL rows; `blank=True` stays — forms may submit empty because
   `save()` mints one, category-based fallback for nameless places),
   plus the grammar/reserved-name validation from D2. The endpoint's
   required `slug` member is then guaranteed at the storage layer.

7. **Extension pattern for future detail blocks.** One optional
   sibling member per detail model (`admin`,
   `transport`, `natural`), gated on `detail_type` +
   row presence + selection, added additively in its own change. No
   wrapper object — sparse fieldsets select flat members and blocks
   arrive independently.

## Risks / Trade-offs

- **Breaking the released geo contract** — accepted by the owner
  (pre-release, zero consumers); mitigated by the registry amendment
  (one clean boundary) and client regeneration.
- **Legacy slug shapes in URLs** (`drinking_water-`, `vending_machine`)
  — stable, grammar-conforming, slightly ugly; normalization rejected
  as churn (revisit only if pretty URLs become a product need).
- **Converter grammar drift** — a future generator change that emits
  pure-word slugs would break the disjointness invariant; guarded by
  the model-layer validation (D2), which rejects such slugs at save
  time.
- **Reserved names grow** — the blacklist is a safety net behind the
  structural rule; the fixed-segment rule (no `-`/`_` in fixed
  segments) is the actual contract, documented in the spec.

## Migration Plan

1. Schema: slug `null=False` `AlterField` + validation; re-mint
   migration for grammar exceptions (expected none).
2. Routing: register the converter, add `places/<geoplace:slug>`,
   switch the SEO siblings, remove `places/amenity/<int:place_id>`.
3. Registry: amend the unreleased `VersionChange`, regenerate the
   snapshot, commit both in the PR.
4. Sequencing vs `geoplace-parties`: either order works; landing
   after (or with) it picks up the parties member and projection fix
   for free.

## Open Questions

None. Identifier policy, routing grammar and the breaking-change
process are all decided; block rollout order (admin next — the model
exists) is a per-change decision.

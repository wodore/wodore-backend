# Design: geoplace-capacity-and-types-via-categories

## Context

GeoPlace associations (`GeoPlaceCategory`) carry two optional fields added
during the multi-category rework but never given semantics: `classifier`
(FK → Category, "e.g. seasonal status") and `extra` (JSON, "category-
specific overflow data"). The hut world needs exactly this shape: every
`Hut` has `hut_type_open` + `hut_type_closed` (both accommodation
categories) and `capacity_open`/`capacity_closed` (bed counts). The
"one category per parent" import rule makes a second `accommodation.*`
association for the closed type impossible — the closed-season meaning is
a *qualification* of the open type, not an equal peer category. The martin
`geoplaces_tiles` view already forwards `gpc.extra` per category entry, so
tile consumers get capacities for free once written.

## Goals / Non-Goals

**Goals:**
- Give `classifier` and `extra` precise, source-agnostic semantics.
- Provide the season vocabulary `hut_type_closed` maps onto.
- Make the wodore hut import populate them (schema-path rewrite included).
- Expose them through API and admin; verify tiles.

**Non-Goals:**
- No new detail model (`AmenityDetail` keeps phones/opening_hours;
  WEP008's `AccommodationDetail` stays "not implemented").
- No availability/booking migration off `Hut` (separate change).
- No OSM-side accommodation import (no accommodation OSM mappings exist).
- No generalized attribute schema/UI for arbitrary `extra` keys beyond
  the two capacity keys (extension point stays, surface stays minimal).

## Decisions

1. **Capacity lives in `GeoPlaceCategory.extra`, not on a detail model.**
   `extra = {"capacity_open": 40, "capacity_closed": 12}` on the
   accommodation association. Alternatives: `AmenityDetail` fields (wrong
   owner — capacity is per-category-classification, not amenity state;
   also would need a second join for tiles) or new `AccommodationDetail`
   (WEP008 explicitly defers it). Association-extra keeps it in the tile
   view's existing payload and merges per-source via the association row.
   Keys are only written when known; `None`-valued keys are dropped, not
   stored (empty dict == no capacity data).

2. **`hut_type_closed` maps to a `classifier`, not a second category.**
   New `season` category parent (children: `winter_room`, `self_service`,
   `year_round`, `closed`, `summer_only`) — classifier references only
   `season.*` categories. Mapping from existing `hut_type_closed` values:
   `selfhut` → `season.self_service`, `bivouac` → `season.winter_room`,
   `closed` → `season.closed`, `camping`/`resta`/`hotel`-family →
   `season.summer_only`, missing → `season.year_round` when the source is
   unguarded year-round, else no classifier (unknown). This follows the
   original design note's example ("category=accommodation.hut,
   classifier=season.winter_room") and preserves the one-per-parent rule.
   Alternative rejected: making the classifier a free-text/enum field —
   loses category machinery (i18n, admin, symbols, future classifiers
   like accessibility grades).

3. **Validation is association-level and cheap.** A `clean()` on
   `GeoPlaceCategory`: `classifier.parent.slug == "season"` (when set);
   capacity keys (if present) are `null` or non-negative ints; unknown
   keys are allowed (forward-compatible) but imports only write the two
   defined keys. No DB constraint beyond the existing unique
   `(geo_place, category)` — JSON flexibility is the point; guards run in
   `save()`/import and admin form, not as Postgres CHECKs.

4. **Import rewrite rides the schema path.** The wodore handler in
   `import_geoplaces` switches from hand-rolled field copying to
   `GeoPlace.update_or_create(schema)` (the OSM import's path), with the
   schema extended to carry per-category `classifier` and `extra`. This
   buys protected-fields/policy handling for free and kills the
   `hut_type_closed`-dropping bug in the current handler. Hut-side mapping
   (`hut_type_closed` → season classifier) lives in the import handler —
   hut-services stays geoplace-agnostic.

5. **API: extend the existing category payload, no new endpoint.**
   `CategoryPlaceTypeSchema` gains optional `classifier: str | None`
   (identifier) and `extra: dict` on the *association* representation in
   search/nearby/detail responses. WEP008's per-detail-type endpoints are
   unaffected (`geo/amenity/{id}` unaffected apart from the same category
   payload gain).

## Risks / Trade-offs

- [Semantics of `extra` keys are conventional, not schema-enforced] →
  Document keys in the spec + validate the two known keys in `clean()`;
  future keys go through a spec delta.
- [Season vocabulary may not fit non-hut accommodation later] → `season.*`
  is generic enough for any accommodation; mapping table lives in the
  import handler, adjustable without model changes.
- [Classifier FK `on_delete=SET_NULL` silently drops classification] →
  Acceptable (degrading to "unknown season" beats breaking deletes);
  admin guards deletion of in-use categories via Django's RESTRICT on the
  category side already.
- [Two hut types collapse into one category + qualifier] → Frontend/API
  consumers can reconstruct `hut_type_closed` semantics from
  `classifier`; document the mapping in the spec for symmetry.

## Migration Plan

1. Data migration: create the `season` parent + children categories
   (slug-fixed, order-stable, no symbols initially).
2. Code: schema extension, association `clean()`, import rewrite, API,
   admin inline, tests — one PR.
3. Backfill: re-run `import_geoplaces -s wodore --update` to populate
   classifier/extra for imported huts (dry-run first; `is_modified`
   places are skipped by policy, as designed).
4. Rollback: associations' new fields are additive JSON/FK on existing
   rows — reverting code + dropping the season categories suffices; no
   destructive migration.

## Open Questions

- Exact `hut_type_closed` → season mapping for the two `unknown`-ish hut
  types (`special`, `resta`) — default: no classifier (unknown) until
  seen in real data.
- Should the tiles view also surface the classifier identifier (today it
  forwards `extra` but not `classifier`)? Lean: add it while we are there
  — one line in the view's JSON build.

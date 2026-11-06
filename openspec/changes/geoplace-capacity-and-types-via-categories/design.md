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

> **Revised after PO review + advisor second opinion** (the original
> single-association design is superseded): the classifier is an
> *operation mode* (`mode.standard`/`mode.reduced`), a hut imports as
> up to two associations, and `extra` is validated by a JSON Schema
> stored in the DB (admin-manageable). Decisions below reflect the
> revised design.

1. **One mode = one association = its own capacity.** A hut imports
   as `(open_type, mode.standard, extra.capacity = capacity_open)`
   and, when a reduced fact is published, `(closed_type,
   mode.reduced, extra.capacity = capacity_closed)`. When only a
   closed capacity is known (closed type absent or `unknown`, but
   `capacity_closed` set — 108 huts in live data), the reduced
   association lands on `accommodation.unknown` so the value is not
   lost; with neither closed type nor capacity there is no reduced
   association. `None`-valued keys are dropped, never stored as
   `null`. Capacity stays off detail models (wrong owner — capacity
   is per-mode, not amenity state; WEP008 defers `AccommodationDetail`).

2. **The classifier is the operation mode; the closed type is the
   second association's category.** Vocabulary: `mode` parent with
   exactly `standard` and `reduced` — these map 1:1 onto the
   availability tiles' `dN_type` classification, giving that change a
   classifier-based classification path instead of the `huts_hut`
   join. The original 5-value `season.*` vocabulary (winter_room,
   self_service, …) re-encoded closed-type *names* that the category
   itself already carries — dropped. The one-per-parent import rule
   is superseded: open and closed types are distinct categories, and
   when they coincide (`unknown`/`unknown`, 3 huts) the unique
   constraint keys on `(geo_place, category, classifier)` with
   `nulls_distinct=False` (PG15+) so both rows coexist.

3. **`extra` is validated by a JSON Schema stored in the DB.** New
   `CategoryExtraSchema` model in `geometries` (keeps the generic
   `Category` clean): `OneToOneField(Category)` + JSON Schema
   (draft 2020-12) JSONB. Resolution walks exactly one level
   (category's own schema, else the parent's) — one schema on the
   `accommodation` parent covers all hut types. **Seeded once by data
   migration (`capacity`: integer ≥ 0, nullable), then
   admin-manageable** — `Organization.props_schema` parity: code owns
   initial setup, admins evolve it (e.g. future `water`/`heating`
   keys — typically nullable). Guardrails (advisor review): the
   schema is checked against the JSON Schema metaschema on save,
   `additionalProperties: false` is rejected (the codebase invariant
   is *preserve unknown keys*), compiled validators are cached per
   `(pk, modified)`, and a corrupt stored schema fails OPEN (loud
   log, no validation) rather than bricking writes — including the
   admin page that would fix it. Rejected alternatives: code-only
   registry (PO wants admin editability), generic `value_int`/
   `value_str` columns (one int per association is exhausted by
   capacity; two attribute homes forever), `jsonschema`-free
   hardcoded keys (no runtime extensibility).

4. **Import rewrite rides the schema path.** The wodore handler in
   `import_geoplaces` switches from hand-rolled field copying to
   `GeoPlace.update_or_create(schema)` (the OSM import's path), with
   the schema extended to carry per-category `classifier` and
   `extra` (`PlaceTypeInput`). This buys protected-fields/policy
   handling for free. The hut-side mapping (two mode entries per the
   rule in decision 1) lives in the import handler — hut-services
   stays geoplace-agnostic. The resolver dedupes per
   `(category, mode)` and the update path keys existing rows the
   same way (advisor P0s: same-category mode pairs must coexist and
   refresh independently); schema-defined keys are source truth on
   update, keys outside the schema are preserved.

5. **API: extend the existing category payload, no new endpoint.**
   `CategoryPlaceTypeSchema` gains optional `classifier: str | None`
   (identifier) and `extra: dict` on the association representation
   in search/nearby/place-detail responses, under the
   `fields[places]` sparse-fieldset selection. A hut place now lists
   two category entries (standard + reduced). The addition is
   additive and is registered in the API changelog per
   `api-conventions` (PR label `api:added`, no version bump). The
   former `get_amenity` `AttributeError` was already fixed by
   `place-detail-endpoint` — nothing to do.

6. **Admin: schema-driven editing, mode-scoped autocomplete.** The
   association inline renders `extra` through Unfold's jedison-based
   `UnfoldAdminJSONSchemaWidget` with the schema resolved per row
   (own category, else parent) — the editor UI is generated from the
   JSON Schema; rows without a schema keep the plain JSON textarea.
   The classifier autocomplete is scoped to the `mode.*` subtree.
   `CategoryExtraSchema` gets its own admin (seeded from code,
   evolved in admin — additive-only discipline documented in the
   field help text). Manual edits keep marking the place
   `is_modified` + flat `"categories"` protection via the
   pre-existing `save_formset` wiring (geoplace-parties D7).

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
- [Association edits are invisible to import policies unless tracked] →
  The admin formset save explicitly updates `is_modified`/
  `protected_fields` (decision 6); without it a re-import would silently
  overwrite manual classifier/capacity edits.

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

- Exact `hut_type_closed` → season mapping for `special` — default: no
  classifier (unknown) until seen in real data. (`resta` is resolved:
  it maps to `season.summer_only` with the `camping`/`hotel` family, per
  decision 2.)
- Tiles: resolved — the `geoplaces_for_tiles` view gains the
  `classifier` identifier next to `extra` (task 3.2); the key lives
  inside the categories JSON, so martin needs no config/schema change.

## Follow-ups (separate changes)

- **AmenityDetail population for huts**: `open_monthly` →
  `opening_months` (identical month-status vocabulary), contact phones →
  `phones`, `url`/contact URLs → external-link associations. The entity
  question is decided in `geoplace-parties`: a neutral **Party** entity
  with `role.*` category classifiers replaces both `AmenityDetail.brand`
  and — via the `import_parties` merge — `hut_owner` (role `role.owner`).
- **`geoplace-availability`**: re-anchor availability on GeoPlace
  (booking-source reference, type-on-date) including how
  `HutAvailability`/`HutAvailabilityHistory` are migrated/preserved, and
  the eventual removal of the `huts` app.

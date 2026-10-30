# Design: geoplace-kind-fk

## Context

PRs #454/#456 established: kind = anchoring category (first by
`(order, slug)`), domain = its super-root tier, the association table
carries classifiers/extras, and the API derives a `kind` ref member
at read time. The PO now wants the anchor stored: `kind` as the
place's category FK, `categories` as sub-categories.

## Decisions

1. **Denormalized anchor (D1), not source-of-truth FK (D2).** The FK
   is stored and indexed, derived on write from the first
   association — the association table remains the source of truth.
   D2 (associations lose the anchor row, classifier/extra move to
   new columns) was rejected: it breaks the #454 contract model
   (classifier validation against the kind's group, two-association
   season semantics: `hut + mode.standard` / `unknown + mode.reduced`
   are two association rows for ONE place), the tiles SQL, and every
   write path — for zero query benefit (both need one indexed
   lookup).

2. **API `kind` member absorbs the anchor's classifier/extra.** The
   anchor association row carries season classification
   (`classifier: mode.*`) and schema-validated attributes (`extra`).
   Moving the row out of the `categories` member without exposing
   these would hide them; the kind member grows
   `classifier`/`extra` (additive, optional members) so
   classification consumers read one member.

3. **`categories` member = sub-categories only.** Excluding the
   anchor ends the duplication (kind appearing in both members).
   Riding the unreleased version — no released consumer expects the
   anchor in `categories`; the frontend typeahead (PR #376) already
   renders `kind` standalone.

4. **Derivation unchanged.** First association by `(order, slug)` —
   the exact rule `__str__`, the tiles JSON ordering, and `domain`
   already use. `anchor_category()` in `kinds.py` is the single
   helper; write paths set `kind` + `domain` together.

5. **`on_delete=SET_NULL`.** Protected vocabulary largely prevents
   kind-category deletion; if a non-protected kind category dies,
   the place keeps its associations (backfill-able) rather than
   cascading.

6. **Admin**: readonly FK link (Unfold renders FK links natively);
   Categories inline stays the editing surface — reordering there
   re-anchors on save.

## Risks / Trade-offs

- [Duplication drift] FK vs first-association can diverge if a write
  path forgets the derivation — mitigated by funneling every path
  through the same helpers (`_resolve_place_types` → spec list →
  derive both facts) and a test pinning FK == first association
  after each write path.
- [`categories` narrowing] Any consumer reading the anchor from
  `categories` must switch to `kind` — unreleased-only surface; the
  registry note documents it.
- [Backfill cost] One chunked UPDATE with a lateral join over
  associations — linear, minutes at 5M places, CONCURRENTLY not
  needed (plain FK add + update).

## Migration Plan

1. `0073_geoplace_kind_fk`: AddField (`kind` nullable FK, indexed) +
   RunPython backfill (`kind = first association by (order, slug)
   per place`) + reverse (SET NULL all).
2. Model code: `kind` FK + `kind_id: int | None` declaration.
3. Write paths: derive + store alongside `domain` (schema upsert,
   OSM bulk, geonames inherits via the schema path).
4. API: `anchor_kinds_for` reads `place.kind_id` (one query on the
   FK, simpler than the association lateral); `kind_ref_for` gains
   classifier/extra from the anchor association;
   `build_categories_data` filters out the anchor row.
5. Admin: fieldset swap (`kind_display` → `kind` FK readonly).

## Follow-ups

- Tiles categories JSON could mark the anchor (icon parity check).
- `hut_slug` discriminator member (staging typeahead follow-up).

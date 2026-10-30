# Proposal: geoplace-kind-fk

## Why

The kind (main category, e.g. `accommodation.hut`) is the primary
classification of a place, but lives only implicitly as "the first
category association by `(order, slug)`" — derived everywhere it is
needed (API `kind` member, admin display, domain derivation), never
stored. The PO wants the hierarchy explicit on the model: **`kind` is
the place's category field (FK); `categories` are sub-categories**
(additional classifications). This makes the anchor a first-class,
queryable, indexed fact instead of a convention.

## What Changes

- **`GeoPlace.kind`** — new nullable FK to `Category`
  (`related_name="places_anchored"`, `on_delete=SET_NULL`,
  indexed). Derived on write from the first category association by
  `(order, slug)` — the exact rule every consumer uses today — and
  stored alongside `domain` (one derivation step, two stored facts).
- **Backfill migration** — `kind = first association per place` for
  all existing places; places without categories stay NULL
  (`domain="none"` already covers them).
- **API** (`search`/`nearby`/`get_place`):
  - `kind` member becomes the authoritative main-category member:
    `{identifier, slug, color, name, symbol, classifier, extra}` —
    it now also carries the anchor association's **classifier**
    (e.g. `mode.standard`) and **extra** (schema-validated
    attributes), so season/classification consumers need no other
    member.
  - `categories` member lists **sub-categories only** (associations
    excluding the anchor kind row) — no more duplication of the main
    category in both members.
  - `domain` unchanged.
- **Admin**: the GeoPlace change form shows `kind` as a readonly FK
  link (replacing the derived `kind_display`); the Categories inline
  remains the editing surface (reordering changes which association
  anchors — re-derivation on save keeps the FK in sync).
- **Write paths**: schema upsert (wodore import), OSM bulk path, and
  geonams derive `kind` + `domain` together from the same spec list;
  protected-fields semantics unchanged (`kind` follows `domain`).

## What does NOT change

- **`GeoPlaceCategory` associations stay the source of truth** for
  classifiers/extras (the #454 contract model — classifier
  validation against the kind's group contract, two-association
  season semantics — keys off association rows). The FK is a
  denormalized anchor, kept in sync on write — same doctrine as
  `domain`.
- **Tiles SQL unchanged** — the categories JSON in
  `geoplaces_for_tiles` keeps listing all associations (tile icons
  need every category; the kind is also a category there).
- **Dedup/category filters** (`types`/`categories`/`kind` params) —
  the `kind` filter now matches the FK directly (cheaper); the rest
  unchanged.

## Capabilities

### Modified

- `geoplace-kind` (new capability spec): the kind FK, derivation
  rule, API member shapes (kind with classifier/extra, categories as
  sub-categories), admin surface.

## Impact

- **Models**: `GeoPlace.kind` (nullable FK, indexed)
- **Migrations**: `0073_geoplace_kind_fk` — AddField + backfill
  (first association per place, chunked) — no destructive operation
- **Code**: `kinds.py` gains `anchor_category()`; write paths store
  `kind_id` next to `domain`; `anchor_kinds_for` reads the FK (one
  query simplification); `build_categories_data` excludes the anchor;
  `kind_ref_for` gains classifier/extra from the anchor association
- **API**: additive members on `kind` (classifier/extra) +
  narrowing of `categories` (anchor row moves out) — the latter is a
  shape change riding the unreleased version (no released consumer
  depends on the anchor appearing in `categories`)
- **Frontend**: wodore-frontend-quasar#376 already renders `kind`
  standalone; sub-category chips simply stop duplicating the main
  category

## Out of scope

- Hut→GeoPlace migration (separate change)
- Tiles/categories JSON shape (documented follow-up if wanted)
- ParadeDB/WEP006 search track

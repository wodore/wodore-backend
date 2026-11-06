# Design: brand-category-cleanup

## Context

`geoplace-parties` (archived as `2026-10-25-geoplace-parties`)
converted every `AmenityDetail.brand` reference into a Party +
`role.brand` association (geometries 0053) and kept the `root.brand`
category subtree "for rollback safety (cleanup in a later change)".
That later change is this one. Deploy of 0053 is through (main + prod),
so the rollback rationale no longer applies.

Reference surfaces checked:

- `GeoPlaceCategory.category` is `on_delete=RESTRICT` — legacy
  association rows would `ProtectError` the delete.
- `Category.parent` is `on_delete=CASCADE` — deleting the `root.brand`
  parent takes its children with it.
- No code references `root.brand` (import, admin, seeds are all
  brand-free since #415); `basemaps`/`images`/`api` "brand" hits are
  the product brand (logo assets), unrelated.

## Goals / Non-Goals

- Goals: remove the dead vocabulary; spec delta reflects it.
- Non-Goals: touching parties, roles, or any other category vocabulary;
  re-deriving anything on reverse.

## Decisions

1. **Associations first, then the subtree, in one migration.** The
   association rows are the only RESTRICT blockers; they are superseded
   by party associations (same meaning, different model). Alternative —
   soft-deactivating the categories — leaves the clutter the change is
   meant to remove.
2. **Delete by identifier, not by pk.** Look up `root.brand` via
   `Category.objects.filter(identifier="root.brand")`; absent → no-op.
   This keeps the migration idempotent across fresh test databases
   (which never had brand categories) and re-runs.
3. **Reverse is a no-op.** The brand categories were minted by the OSM
   import on the fly — not re-derivable from the Party rows (which also
   merged owners and operator parties in the meantime).

## Risks / Trade-offs

- [A place's category association is deleted that an editor still
  wanted] → Mitigation: only associations whose category sits under
  `root.brand` are deleted; every one of them was written by the legacy
  brand import and has a party counterpart from 0053.
- [Migration races concurrent category creation under `brand`] →
  Mitigation: nothing creates those categories anymore (code removed in
  #415); the migration runs in a deploy window anyway.

## Migration Plan

1. Ship the data migration; `migrate` on deploy removes associations,
   then the subtree.
2. Lane dry-run before shipping (counts before/after); unit test seeds
   the legacy tree and asserts removal + survival of `role.*`.

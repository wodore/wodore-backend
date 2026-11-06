# Proposal: Adopt django-readers query optimization

## Summary

Replace hand-rolled ORM optimization (manual `select_related`/`prefetch_related`/`only()` plus ~120 lines of `JSONBAgg`/`JSONObject` annotations) with spec-driven query generation, keeping our pydantic response schemas as the single source of truth and benchmarking hot paths before touching them.

## Why

- **Three serialization paths for the same model** (hut detail, search list, geo endpoints) each hand-maintain their own annotation/prefetch set — divergence bugs and copy-paste drift.
- **Every new field needs four edits**: DTO schema, annotation, `field_selected()` gate, projection entry. The sparse-fieldsets work made this mechanical but not automatic.
- **N+1s are only preventable by discipline** — nothing fails when a `prefetch_related` is forgotten.
- dmr's docs recommend [django-mantle](https://noumenal.es/mantle/) for this problem; its engine is [django-readers](https://www.django-readers.org). Mantle's shape classes are `attrs`, but our response schemas are pydantic (aliases, validators, `from_attributes`) — the decision to keep pydantic was taken during the dmr migration.

## What Changes

- Add a small derivation layer: pydantic response schema → django-readers spec (FK/nested-model fields → relationship entries, plain fields → field entries, sparse `fields[TYPE]` selections → spec subsets).
- Convert cold endpoints first (hut detail `get_hut`, categories, organizations, symbols detail paths) to generated queries.
- Benchmark the hot paths (`search_huts`, `huts.geojson`, geo search/nearby) — hand-tuned `JSONBAgg` aggregation vs readers-generated queries — and only convert them at parity or better.
- Computed/aggregated fields (distance, availability, `JSONBAg` collections) stay as explicit reader pairs (django-readers' `@overrides`-equivalent: custom `(prepare, project)` pairs), not generated.

## Capabilities

### Modified

- `cold-query-optimization`: hut detail and secondary endpoints derive queries from schemas instead of manual annotation sets.

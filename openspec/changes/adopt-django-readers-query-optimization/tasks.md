# Tasks: Adopt django-readers query optimization

## 1. Derivation layer

- [x] 1.1 Add `django-readers` dependency (version pin in `pyproject.toml`, `uv sync --extra private`)
- [x] 1.2 Implement `spec_from_schema(schema, fields=None, overrides=None)` in `server/apps/api/readers.py`: plain fields → field entries; nested models with matching relations → relationship entries; sparse `fields[TYPE]` selection → spec subset; `overrides` → verbatim reader pairs
- [x] 1.3 Unit tests: derived specs for representative schemas (flat, FK-nested, reverse-FK-nested, sparse-subset, override) asserting spec shape and processed queryset SQL column/relation set

Findings baked into the implementation (both anticipated by the design's "`only()` vs shared code" trap):

- **modeltrans trap 1**: `only('relation_name')` implies `select_related` traversal; the multilingual queryset then defers sibling translated fields (e.g. `Category.symbol_detailed`) and Django rejects "cannot be both deferred and traversed". Forward to-one relations therefore emit a custom prefetch pair that includes only the `<name>_id` column instead.
- **modeltrans trap 2**: any `only()` without `i18n` defers the TranslationField, breaking translated attribute reads — `_include_i18n()` keeps it in every derived spec for models that carry it.
- **manager defaults**: `Category._default_manager` pre-applies `select_related('parent', 'symbol_*')`; derived child querysets clear it (`select_related(None)`), since it collides with child field limiting.
- Forward-FK prefetch on an all-NULL column skips the child query entirely (Django behaviour) — nullable FKs cost nothing extra.

## 2. Pilot: hut detail

- [ ] 2.1 Convert `get_hut` (`server/apps/huts/api/_hut.py`) to a derived spec; move `annotate_hut_sources()`/`annotate_hut_images()` bodies into reader pairs (same SQL)
- [ ] 2.2 Query-count test pinning `get_hut` at or below its current count
- [ ] 2.3 ETag/304 behaviour unchanged (contract test re-run; ETag key inputs untouched)

## 3. Roll out cold endpoints

- [x] 3.1 Categories endpoints — in-memory tree assembly: cold build went from ~9000 queries (per-node children/symbol/parent lazy loads, hidden only by the page cache) to ONE query (symbols + parent joined, children grouped in memory); cold + warm query pins added
- [x] 3.2 Organizations/symbols detail paths — symbols: relation loading now schema-derived (relations_only + select_related_for; the dead uploaded_by_user join is gone; 1-query pin). Organizations: nothing to derive — the wire schema exposes no relations (already 1 query), documented
- [ ] 3.3 Availability endpoints — follow-up: the two select_related sites follow the now-mechanical symbols pattern; needs its wire-schema analysis first
- [x] 3.4 Query-count tests for each converted endpoint (tests/apps/api/test_cold_query_pins.py: symbols cold pin, categories cold pins + warm-hit-must-be-free)

Phase 3 findings baked into readers.py: ``relations_only`` mode (derive the relation set only — no ``only()`` field limiting, since dump_sparse/from_attributes validates the full schema off the instance and deferred columns lazy-load per row) with ``select_related_for`` join opt-in; scalar-typed relation fields (``license: int``) still load under from_attributes and are now derived as loads, not rejected.

## 4. Benchmark gate: hot paths

- [ ] 4.1 Benchmark harness as a management command (`app benchmark_readers`) comparing hand-tuned vs readers-generated for `search_huts`, `huts.geojson`, geo search/nearby (warm cache, N=50, p50/p95 output)
- [ ] 4.2 Run harness on a lane DB with the `wodore_template` data snapshot; record results in `_work/`
- [ ] 4.3 Per endpoint: convert if p50 within ±5% and p95 not worse; otherwise keep annotations and document the decision at the query site
- [ ] 4.4 If converted: query-count tests as in 2.2

## 5. Cleanup

- [ ] 5.1 Delete annotation/prefetch code paths superseded by derived specs (verify no remaining references)
- [ ] 5.2 Remove hand-maintained `field_selected()` gates that the spec subset now covers (keep the helper where it guards non-query behavior)
- [ ] 5.3 Update `_work/` session document with benchmark numbers and final endpoint disposition table
# trigger

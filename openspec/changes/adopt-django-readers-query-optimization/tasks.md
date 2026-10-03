# Tasks: Adopt django-readers query optimization

## 1. Derivation layer

- [ ] 1.1 Add `django-readers` dependency (version pin in `pyproject.toml`, `uv sync --extra private`)
- [ ] 1.2 Implement `spec_from_schema(schema, fields=None, overrides=None)` in `server/apps/api/readers.py`: plain fields → field entries; nested models with matching relations → relationship entries; sparse `fields[TYPE]` selection → spec subset; `overrides` → verbatim reader pairs
- [ ] 1.3 Unit tests: derived specs for representative schemas (flat, FK-nested, reverse-FK-nested, sparse-subset, override) asserting spec shape and processed queryset SQL column/relation set

## 2. Pilot: hut detail

- [ ] 2.1 Convert `get_hut` (`server/apps/huts/api/_hut.py`) to a derived spec; move `annotate_hut_sources()`/`annotate_hut_images()` bodies into reader pairs (same SQL)
- [ ] 2.2 Query-count test pinning `get_hut` at or below its current count
- [ ] 2.3 ETag/304 behaviour unchanged (contract test re-run; ETag key inputs untouched)

## 3. Roll out cold endpoints

- [ ] 3.1 Categories endpoints
- [ ] 3.2 Organizations/symbols detail paths
- [ ] 3.3 Availability endpoints
- [ ] 3.4 Query-count tests for each converted endpoint (same pattern as 2.2)

## 4. Benchmark gate: hot paths

- [ ] 4.1 Benchmark harness as a management command (`app benchmark_readers`) comparing hand-tuned vs readers-generated for `search_huts`, `huts.geojson`, geo search/nearby (warm cache, N=50, p50/p95 output)
- [ ] 4.2 Run harness on a lane DB with the `wodore_template` data snapshot; record results in `_work/`
- [ ] 4.3 Per endpoint: convert if p50 within ±5% and p95 not worse; otherwise keep annotations and document the decision at the query site
- [ ] 4.4 If converted: query-count tests as in 2.2

## 5. Cleanup

- [ ] 5.1 Delete annotation/prefetch code paths superseded by derived specs (verify no remaining references)
- [ ] 5.2 Remove hand-maintained `field_selected()` gates that the spec subset now covers (keep the helper where it guards non-query behavior)
- [ ] 5.3 Update `_work/` session document with benchmark numbers and final endpoint disposition table

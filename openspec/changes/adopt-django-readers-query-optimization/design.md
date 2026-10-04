# Design: Adopt django-readers query optimization

## Context

dmr documents django-mantle (attrs + django-readers + cattrs) as the recommended queryset layer, with a one-line controller integration. Our stack standardized on pydantic during the dmr migration (18 alias fields, 8 validators, 6 model_validators, 8 `from_attributes` usages). This design settles the integration shape and the migration order.

## Goals / Non-Goals

Goals:
- One declared response shape drives schema, query, and projection.
- Query-count regressions fail tests, not production.
- Keep pydantic as the OpenAPI source of truth.
- Zero performance regression on hot endpoints; convert them only at measured parity or better.

Non-Goals:
- JSON:API compliance, changing wire formats, or response shape changes.
- Replacing `JSONBAgg` aggregation where it measurably wins for list endpoints.
- Writing (creating/updating) endpoints — read paths only.

## Decision: Option C — django-readers directly, pydantic-derived specs

Options considered:

1. **Full mantle (attrs shapes)** — first-class dmr support, but splits the OpenAPI source of truth between pydantic response schemas and attrs shape classes. Our `WodoreSerializer` (`exclude_unset`) can't serialize attrs instances; we'd maintain two parallel type systems.
2. **Mantle + bridge** — attrs shapes converted into our pydantic schemas before returning. Keeps one wire truth but pays double validation (cattrs struct + pydantic validation) on every response, and still duplicates the shape declarations.
3. **django-readers with pydantic-derived specs (chosen)** — mantle's engine without its cattrs glue. A derivation function (~100 lines) walks our existing pydantic response schemas and emits a readers spec:
   - plain field → `("field_name",)` entry
   - nested pydantic model whose name maps to a FK/reverse relation → relationship entry (`{"relation": [...]}`)
   - sparse `fields[TYPE]` selection → spec subset (composes with the existing `field_selected()` helpers — they stop being maintained by hand)

   Same optimization guarantees (`only()`/`defer()`/prefetch, no N+1), pydantic stays single-source, and computed fields are explicit django-readers pairs.

### Risks / Trade-offs

- **We own the derivation layer.** Mitigation: it's small, typed, and covered by query-count tests; mantle remains a reference implementation to borrow from.
- **Relation detection heuristics** (which nested model is a relation) could mis-derive. Mitigation: explicit per-endpoint overrides (`spec_overrides=`) before any magic; heuristics only where unambiguous (`model._meta` field-name match).
- **Readers-generated queries may lose to `JSONBAgg` on wide list endpoints** (single query vs select+prefetch). Mitigation: benchmark gate below; hot endpoints keep annotations.

#### Mixing readers and hand-coded paths (verified against django-readers docs)

Specs are pure functions (`process(spec) → (prepare, project)`) with no global state, no `INSTALLED_APPS` registration, no settings — adoption is per-endpoint and JSONBAgg/ readers paths never share a queryset. Three concrete failure modes to guard, each pinned by the query-count tests:

1. **prepare/project split**: calling `project()` on a queryset that skipped `prepare()` → deferred-field access triggers silent per-instance queries (N+1) or `AttributeError` on a missing `to_attr`. The derivation always returns the pair together.
2. **`only()` vs shared code**: model methods, `__str__`, or signal handlers touching fields outside the spec cause per-instance deferred loads. Readers has explicit cookbook patterns for properties/methods requiring loaded fields — use them; the query-count tests catch violations.
3. **Annotation name collisions**: an annotated attribute (`.sources`) and a spec relationship with the same name on one queryset collide. Computed fields become reader pairs (annotation inside `prepare`), so both names never coexist on one path; shared annotating manager methods stay out of readers endpoints.

#### Ecosystem check (no pydantic wrapper exists)

- **django-mantle**: attrs + cattrs — no pydantic support.
- **`django_readers.rest_framework`**: derives DRF serializers *from* specs (opposite direction) for OpenAPI introspection; targets DRF, not dmr/pydantic.
- **django-modern-schemas** (dmr-docs companion): generates pydantic models *from* Django models — solves the schema side, not query optimization; our schemas already exist hand-authored.

The pydantic→spec derivation is therefore ours to own (~100 lines). The inverse direction (spec→pydantic, à la the DRF module) was considered and rejected: specs are pure query shape and cannot carry OpenAPI metadata (descriptions, examples, aliases) that our hand-authored schemas must keep.

#### Reversibility

The layer is one isolated module plus per-endpoint call sites — no migrations, no settings, no shared state. Reader pairs are plain `(prepare, project)` functions whose bodies come straight from the current annotations. Dropping = revert endpoints, delete the module, remove the dependency; query-count tests document correct counts for both implementations, making the revert verifiable. Partial adoption (hot endpoints keeping `JSONBAgg` indefinitely) is a supported stable end-state, not a failure.

## Surprising Details

- The `@spec`/`@overrides` escape hatches map exactly onto our existing computed annotations (`annotate_hut_sources()`, `annotate_hut_images()`) — they become reusable reader pairs with the same bodies, so the hand-tuned logic isn't discarded, it's re-expressed.
- ETag keys on hut endpoints hash the resolved version + registry — none of that changes; readers only touches the query construction inside `get_hut`.

## Migration Plan

1. **Derivation layer + tests** (`server/apps/api/readers.py`): `spec_from_schema(schema, fields=None, overrides=None)`; unit tests asserting generated specs and resulting query SQL/counts against the current hand-tuned equivalents.
2. **Pilot on hut detail** (`get_hut`): the 12 manual `select_related`/`prefetch_related` decisions and annotation gating become one derived spec; query-count test pins it (must be ≤ current count).
3. **Roll out to cold endpoints** (categories, organizations/symbols detail, availability) — mechanical after the pilot.
4. **Benchmark gate for hot paths**: harness compares `search_huts`, `huts.geojson`, geo search/nearby across both implementations (warm cache, N=50 runs, p50/p95). Convert only if p50 within noise (±5%) and p95 not worse; otherwise document the keep-annotations decision in the code.
5. **Delete superseded annotation code** once no endpoint references it.

## Open Questions

- Benchmark harness placement: standalone management command (`app benchmark_readers`) vs pytest-benchmark in CI vs a manual script under `scripts/`. Leaning management command — reproducible against any lane DB, CI-optional.
- Whether the derivation layer should live in `server/apps/api/` (shared infra) or per-app — leaning shared, mirroring `projection.py`/`query.py`.

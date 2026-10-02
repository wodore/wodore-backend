# Design: switch-to-sparse-fieldsets

## Context

- House rules: one codebase, newest shape; older versions produced by
  transforms at the edge (apiversions). Any observable wire change needs a
  `VersionChange`.
- Current narrowing: `FieldsQuery` (include/exclude strings) →
  `include_set()` against the response schema's model_fields →
  `model_dump(include=...)` (server/apps/api/query.py).
- dmr: typed query models via `Query[Model]`; pydantic DTOs serialize with
  `WodoreSerializer` (`exclude_unset`).

## Goals / Non-Goals

- Goals: JSON:API-conformant `fields[TYPE]`; type-scoped nesting; 400 on
  unknown types/fields; deprecation path for include/exclude; frontend can
  derive narrowed types from the generated schema types.
- Non-Goals: GraphQL-style arbitrary nesting depth (one level of type
  scoping); changing default field sets per endpoint.

## Decisions

### D1 — Parameter shape: `fields[TYPE]=a,b` (JSON:API)

`?fields[huts]=slug,name&elevation`-style is the spec'd form; `TYPE` maps to
the DTO class name normalized to snake_case plural as used in
`components.schemas` (e.g. `huts` → `HutSchemaDetails`, `sources` →
`OrganizationBaseSchema`). A compatibility alias `fields[hut]` is NOT
added — one spelling per type.

### D2 — Parsing: one typed model per endpoint (dmr-native)

dmr query models are pydantic classes; bracket parameters are not valid
Python identifiers, so `fields[huts]` cannot be a field name. Parse at the
component level: a custom pydantic field `fields: dict[str, str] | None`
plus a **before-validator** that collects all `fields[*]` keys from the raw
query dict into the mapping. The validator rejects unknown types with 400
(`invalid_field_type`). This keeps the dmr pattern (typed model, declarative
docs via a companion `x-field-types` extension listing valid types).

### D3 — Projection: DTO-driven, serialization-time

`include_set()` today keys on the top schema. Replace with
`Fieldsets.projection(dto_cls, fields_map)`:
- top-level DTO class resolved from the endpoint's response type
- nested types resolved by walking DTO annotations (list[X], X | None)
- each `fields[TYPE]` entry validated against that DTO's `model_fields`
- produces `model_dump(include=...)` sets per nesting level; required fields
  always kept (as today)

### D4 — Deprecation mechanics for include/exclude

- OpenAPI: mark `include`/`exclude` params `deprecated: true` with the
  replacement note (dmr `@modify` parameter metadata).
- Runtime: endpoint-level deprecation entries already exist for other cases
  (registry `ENDPOINT_DEPRECATIONS` announce headers per endpoint); reuse
  the same header mechanism via a dedicated `PARAMETER_DEPRECATIONS` table
  announcing `Deprecation`/`Sunset`/`Link` on responses of endpoints that
  receive include/exclude — 6-month sunset after the fields rollout,
  matching the bookings precedent.

### D5 — Versioning: accepted everywhere, removed versioned

`fields` is additive (no version needed to accept). Removing
include/exclude IS breaking → lands as a `VersionChange` whose transforms
translate `include`/`exclude` query semantics? No — request transforms do
not apply to query params in this system. Instead: include/exclude keep
answering for all existing versions; the removal registers a NEW version
and the OpenAPI snapshots per version document which parameters exist.
Clients pinned to old versions keep include/exclude indefinitely (their
snapshots say so); new versions document only `fields`.

### D6 — Frontend typing (the user's question)

OpenAPI cannot express "response shape depends on query param". The
generated types stay the FULL schema; narrowing is a client-side type
derivation on top of them:

```ts
type Sparse<T, K extends keyof T> = Pick<T, K>;
// usage with the generated components:
type HutCard = Sparse<schemasWodore['HutSchemaDetails'], 'slug' | 'name' | 'elevation'>;
```

The backend ships this as a documented pattern (and the typegen CI gate
keeps the full types valid). Optionally later: a tiny
`getSparse<T, K>(url, fields)` fetch helper in `src/clients/` that
constructs `fields[...]` from K at runtime — then the correlation is
compiler-enforced. Server-side JSON-schema narrowing is NOT attempted
(it would fork the schema per request; not expressible).

## Risks / Trade-offs

- Bracket params and some HTTP caches/CDNs: `fields[huts]` contains
  reserved chars `[]` — must be percent-encoded by clients; document it.
- Two narrowing systems coexist during the deprecation window; the
  projection helper is shared so behavior cannot diverge.
- pydantic `model_fields` remain the allowlist source (single truth).

## Migration Plan

1. Implement `fields[TYPE]` + projection helper + tests (behavior parity
   with include/exclude for the same selections).
2. Deprecate include/exclude (headers + schema).
3. On the NEXT registered version after rollout+6 months: remove
   include/exclude, regenerate snapshots, `VersionChange` documents it.

## Open Questions

- Type names in brackets: plural (`fields[huts]`) vs schema name
  (`fields[HutSchemaDetails]`)? → plural, JSON:API convention.

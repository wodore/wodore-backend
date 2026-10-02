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
  unknown types/fields; direct removal of include/exclude (no consumer);
  Swagger-UI-visible documentation; frontend can
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
(`invalid_field_type`).

### D2a — Swagger UI documentation (deepObject)

dmr's parameter generator has no `deepObject` support (verified against
0.16) and would render a bare `dict` as an opaque object. Document the
parameter properly via the schema post-processing hook we already own
(`api_v1.get_openapi_schema` — same place that prefixes operation
titles): for every `fields` query parameter, set
`style: deepObject, explode: true` and enrich the description with the
endpoint's valid `TYPE` names. Swagger UI then renders `fields` as a
key/value editor where a tester types `huts` → `slug,name`. This is the
OpenAPI-standard encoding of JSON:API bracket params — no custom UI, no
per-type literal parameter spam (`fields[huts]`, `fields[sources]`, … as
separate rows would work too, but duplicates the type list in every
endpoint and scales poorly).

### D3 — Projection: DTO-driven, serialization-time

`include_set()` today keys on the top schema. Replace with
`Fieldsets.projection(dto_cls, fields_map)`:
- top-level DTO class resolved from the endpoint's response type
- nested types resolved by walking DTO annotations (list[X], X | None)
- each `fields[TYPE]` entry validated against that DTO's `model_fields`
- produces `model_dump(include=...)` sets per nesting level; required fields
  always kept (as today)

### D4 — include/exclude: direct removal (sunset = 0)

No consumer exists (frontend verified; external consumers unknown but the
API is pre-launch). Deprecation theatre would buy nothing: the parameters
are **removed in the change**. The removal IS the breaking change that
registers the new `VersionChange`. Stale clients sending `include`/
`exclude` to the new version get `400 invalid_parameter` (dmr ignores
unknown query keys by default — the query models explicitly reject them
with `extra="forbid"` on the legacy names) so misuse fails loudly instead
of silently returning un-narrowed payloads.

### D5 — Versioning

`fields` is additive (accepted everywhere immediately). Removing
include/exclude registers the NEW version: its snapshot documents only
`fields`; old versions' frozen snapshots keep documenting include/exclude,
and pinned clients keep getting them for as long as their version is
supported. One codebase, newest shape — the projection helper implements
only `fields`; include/exclude on old versions is handled by the snapshot
contract, not by parallel code paths (the parameters are simply gone from
the query models; old-version clients sending them receive the documented
old snapshot's parameters... no — see D4: they receive 400 per the NEW
version's contract when unpinned; pinned-old clients never send fields at
all. The 400 is documented in the new version's schema).

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
- Single narrowing system only (no coexistence window) — simpler, but any
  unknown external consumer breaks loudly at the 400; accepted
  deliberately (pre-launch, sunset = 0).
- pydantic `model_fields` remain the allowlist source (single truth).

## Migration Plan

1. Implement `fields[TYPE]` + projection helper + tests.
2. Remove `include`/`exclude` from the query models; new `VersionChange`;
   regenerate snapshots; changelog entries.

## Open Questions

- Type names in brackets: plural (`fields[huts]`) vs schema name
  (`fields[HutSchemaDetails]`)? → plural, JSON:API convention.

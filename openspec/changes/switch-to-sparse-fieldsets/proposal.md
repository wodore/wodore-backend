## Why

The include/exclude query parameters predate the API versioning system and have three problems:

1. **`exclude` is a contract hazard**: "everything except X" silently grows the payload every time the server adds a field, and new fields reach clients that never opted into them.
2. **Unscoped selection**: `include` applies to the top-level schema only — ambiguous for responses with nested resources.
3. **No frontend typing**: the parameters are loose strings; neither the OpenAPI schema nor the generated TypeScript types can express "this response is a subset of X".

The JSON:API specification standardizes this pattern as **sparse fieldsets** (`?fields[huts]=slug,name,elevation`): positive-only, type-scoped, validated against an allowlist. Switching aligns Wodore with the established REST convention and makes the narrowing expressible in tooling. The frontend never sends include/exclude today (verified), so the blast radius is external consumers only — and the API versioning system exists exactly to announce such a change.

## What Changes

- New query parameter `fields[<type>]=name1,name2` on the endpoints that currently accept `include`/`exclude` (organizations, symbols, huts detail, hut types), following JSON:API sparse fieldsets:
  - positive selection only (no `exclude`)
  - type-scoped (`fields[huts]` vs `fields[sources]`); unknown type bracket is a 400
  - unknown field names are a 400 (allowlist, as today)
  - `__all__` keeps working as the explicit full selection
- `include`/`exclude` keep working but are **deprecated** (Deprecation/Sunset headers, OpenAPI `deprecated: true` on the parameters) and are removed one version later.
- The narrowing moves from response-schema projection to **serialization-time projection driven by the DTO type** (`model_dump(include=...)` keyed by the declared response type), so `fields[huts]` applies to the hut DTO and `fields[sources]` to nested source DTOs independently.
- Registered as a **breaking change** (new `VersionChange`): clients pinned to older versions keep the include/exclude-only behavior; the fields parameter is accepted in all versions but the removal of include/exclude lands with the version after next.

## Capabilities

### New Capabilities
- `sparse-fieldsets`: JSON:API-style `fields[TYPE]` sparse fieldset query parameter with type scoping, allowlist validation, and DTO-driven serialization projection.

### Modified Capabilities
- `include-exclude-narrowing` (existing include/exclude parameters): deprecated with Sunset headers, pinned clients unaffected until their version sunsets.

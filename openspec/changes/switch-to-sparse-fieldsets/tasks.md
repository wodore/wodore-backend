# Tasks: switch-to-sparse-fieldsets

## 1. Core projection

- [ ] Add `Fieldsets.projection(dto_cls, fields_map)` to
      `server/apps/api/query.py`: type resolution over DTO annotations,
      per-type allowlist validation, `__all__` handling, required-field
      retention; unit tests for each behavior
- [ ] Typed query component: `fields` dict field with a before-validator
      collecting `fields[*]` query keys; 400 errors `invalid_field_type` /
      `invalid_field_name` reusing the error contract

## 2. Endpoints

- [ ] Port organizations (list/detail), symbols (4 endpoints), hut detail,
      hut types to the `fields` component and **remove include/exclude**
      from their query models (`extra="forbid"` on the legacy names →
      400 `invalid_parameter` naming the replacement); parity tests:
      same selection via `fields[TYPE]` as include/exclude produced before
- [ ] Schema post-processing: set `style: deepObject, explode: true` on
      every `fields` query parameter and enrich the description with the
      endpoint's valid `TYPE` names (Swagger UI renders a key/value editor)

## 3. Release

- [ ] New `VersionChange` (include/exclude removal is the breaking
      change); regenerate snapshots; changelog entries in BOTH changelogs;
      labels `type:feature` + `api:breaking`
- [ ] Frontend helper (separate PR in wodore-frontend-quasar): documented
      `Sparse<T, K>` type pattern in the clients README

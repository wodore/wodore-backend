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
      hut types to the `fields` component while keeping include/exclude
      (shared projection helper, behavior-parity tests: same selection →
      same response body via either syntax)
- [ ] Document valid `TYPE` names per endpoint (OpenAPI description +
      `x-field-types` extension)

## 3. Deprecation

- [ ] `PARAMETER_DEPRECATIONS` table in apiversions registry announcing
      Deprecation/Sunset/Link headers when include/exclude are received
      (sunset: rollout + 6 months, bookings precedent)
- [ ] Mark include/exclude `deprecated: true` in the schema; frontend
      regeneration verified via the api-types CI gate

## 4. Release

- [ ] Register the `VersionChange` whose version removes include/exclude
      from the documented parameters; regenerate snapshots; changelog
      entries in BOTH changelogs; labels `type:feature` + `api:deprecated`
- [ ] Frontend helper (separate PR in wodore-frontend-quasar): documented
      `Sparse<T, K>` type pattern in the clients README

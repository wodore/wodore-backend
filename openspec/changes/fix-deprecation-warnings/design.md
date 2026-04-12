## Context

The project uses two libraries with deprecated APIs that generate warnings on every test run:

1. **django-health-check 3.24.0** - The plugin-based API (`health_check.db`, `health_check.cache`, `health_check.storage` apps + `health_check.urls`) is deprecated. The v4 migration guide recommends switching to view-based checks with an explicit `checks` list.

2. **Pydantic V2** (used via Django Ninja) - Extra keyword arguments on `Field()` are deprecated. The `example=` and `include_in_schema=` kwargs must move to `json_schema_extra`.

Current state:
- `INSTALLED_APPS` includes `health_check`, `health_check.db`, `health_check.cache`, `health_check.storage`
- `server/urls.py` uses `from health_check import urls as health_urls` with `path("health/", include(health_urls))`
- `server/apps/utils/api.py` uses `Field(..., example="...")` in `VersionSchema` and `Field(None, include_in_schema=False)` in `FieldsSchema`

## Goals / Non-Goals

**Goals:**
- Eliminate all 12+ deprecation warnings from test output
- Use the recommended v4 view-based health check API
- Use the recommended `json_schema_extra` for Pydantic fields
- Maintain identical API behavior (no functional changes)

**Non-Goals:**
- Upgrading django-health-check package version (current 3.24.0 already has the v4 API available)
- Adding new health check types or changing check behavior
- Refactoring the `FieldsSchema` / `fields_query` pattern

## Decisions

### 1. Health check migration approach

**Decision**: Replace plugin-based apps and URL import with explicit `HealthCheckView` and `checks` list.

**Rationale**: The migration guide (v3→v4) recommends removing sub-apps from `INSTALLED_APPS` and using `HealthCheckView.as_view(checks=[...])` with explicit check classes. This eliminates all health_check deprecation warnings.

**Changes**:
- Remove `health_check.db`, `health_check.cache`, `health_check.storage` from `INSTALLED_APPS` (keep `health_check` base app)
- In `urls.py`: replace `from health_check import urls` + `include()` with `HealthCheckView.as_view(checks=[DatabaseCheck, CacheCheck, StorageCheck])`

### 2. Pydantic Field example migration

**Decision**: Replace `example="value"` with `json_schema_extra={"example": "value"}`.

**Rationale**: Pydantic V2 requires `json_schema_extra` for non-standard Field parameters. This is the officially recommended migration path.

### 3. Pydantic Field include_in_schema migration

**Decision**: Replace `include_in_schema=False` with `json_schema_extra={"include_in_schema": False}`.

**Rationale**: Same Pydantic V2 migration - extra kwargs on Field are deprecated. Note: if Django Ninja provides `include_in_schema` natively on its Schema, we may need to use `Field(exclude=True)` or Ninja's own mechanism instead.

## Risks / Trade-offs

- **Health check URL path unchanged**: The `/health/` endpoint remains the same, so no external impact.
- **Pydantic schema shape**: Using `json_schema_extra` should produce the same OpenAPI schema output. If Django Ninja handles `json_schema_extra` differently, the OpenAPI docs may change slightly.

## Why

Running `pytest -v` produces 12+ deprecation warnings from two sources: (1) `django-health-check` v3.x plugin-based API is deprecated in favor of the v4 view-based API, and (2) Pydantic V2 no longer supports extra keyword arguments on `Field()` (e.g., `example=` and `include_in_schema=`). These warnings clutter test output, mask real issues, and will break when the deprecated APIs are removed.

## What Changes

- Migrate `django-health-check` from plugin-based (v3) to view-based (v4) API:
  - Remove `health_check.db`, `health_check.cache`, and `health_check.storage` from `INSTALLED_APPS`
  - Replace `health_check.urls` import in URL config with explicit `HealthCheckView` using `checks` list
- Fix Pydantic `Field()` deprecation warnings in `server/apps/utils/api.py`:
  - Replace `example=` keyword args with `json_schema_extra` dict
  - Replace `include_in_schema=` keyword arg with `json_schema_extra`

## Capabilities

### New Capabilities

_None_

### Modified Capabilities

_None_

## Impact

- `server/settings/components/common.py` - INSTALLED_APPS changes (remove 3 health_check sub-apps)
- `server/urls.py` - Replace deprecated health_check URL import with view-based config
- `server/apps/utils/api.py` - Fix 6 Pydantic Field() deprecations
- No API behavior changes - all endpoints remain functionally identical
- No breaking changes for consumers

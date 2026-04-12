## 1. Fix Pydantic Field deprecation warnings

- [x] 1.1 Replace `example=` keyword args with `json_schema_extra` in `VersionSchema` (`server/apps/utils/api.py` lines 59-76)
- [x] 1.2 Replace `include_in_schema=False` with `json_schema_extra` in `FieldsSchema` and `fields_query` (`server/apps/utils/api.py` lines 99 and 142)

## 2. Migrate health_check to view-based API

- [x] 2.1 Remove `health_check.db`, `health_check.cache`, `health_check.storage` from `INSTALLED_APPS` in `server/settings/components/common.py`
- [x] 2.2 Replace deprecated `health_check.urls` import in `server/urls.py` with explicit `HealthCheckView` using `checks` list

## 3. Verify

- [x] 3.1 Run `pytest -v` and confirm zero deprecation warnings

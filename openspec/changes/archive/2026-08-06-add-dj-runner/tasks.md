## 1. Dependencies and Configuration

- [x] 1.1 Add `django-q2` and `django-admin-runner[django-q2,unfold]` to pyproject.toml dependencies
- [x] 1.2 Install the new packages (`uv sync`)
- [x] 1.3 Add `django_q` and `django_admin_runner` to `INSTALLED_APPS` in `server/settings/components/common.py`
- [x] 1.4 Add `Q_CLUSTER` config (ORM broker) and `ADMIN_RUNNER_BACKEND = "django-q2"` to settings
- [x] 1.5 Run migrations for django-q2 and django-admin-runner (`app migrate`)

## 2. Register Management Commands

- [x] 2.1 Add `@register_command(group="Availability")` to `update_availability` command
- [x] 2.2 Add `@register_command(group="Categories")` to `category_sync_assets` command
- [ ] 2.3 Add `@register_command(group="Computed Fields")` to `updatedata` command — SKIPPED: command is from third-party `computedfields` package, not local code
- [x] 2.4 Add `@register_command(group="External Geonames")` to `import_boundaries` command
- [x] 2.5 Add `@register_command(group="External Geonames")` to `import_features` command
- [x] 2.6 Add `@register_command(group="External Geonames")` to `import_geonames` command
- [x] 2.7 Add `@register_command(group="External Geonames")` to `import_hierarchy` command
- [x] 2.8 Add `@register_command(group="External Links")` to `check_external_links_health` command
- [x] 2.9 Add `@register_command(group="Geometries")` to `geoplaces_import_osm` command
- [x] 2.10 Add `@register_command(group="Geometries")` to `import_geoplaces` command
- [x] 2.11 Add `@register_command(group="Geometries")` to `martin_clean_cache` command
- [x] 2.12 Add `@register_command(group="Huts")` to `hut_sources` command
- [x] 2.13 Add `@register_command(group="Huts")` to `hut_types` command
- [x] 2.14 Add `@register_command(group="Huts")` to `huts` command
- [x] 2.15 Add `@register_command(group="Huts")` to `martin_sync` command
- [x] 2.16 Add `@register_command(group="Licenses")` to `licenses` command
- [x] 2.17 Add `@register_command(group="Meteo")` to `import_meteoswiss` command
- [x] 2.18 Add `@register_command(group="Meteo")` to `import_weather_icons` command
- [x] 2.19 Add `@register_command(group="Organizations")` to `organizations` command

## 3. Admin Configuration

- [x] 3.1 Create custom django-q2 admin classes (Unfold-styled Schedule, Success, Failure, OrmQ) with command dropdown in Schedule
- [x] 3.2 Update Unfold sidebar in `server/settings/components/unfold.py` to add Command Runner and Scheduled Tasks navigation

## 4. Verification

- [x] 4.1 Run the test suite (`inv tests`) to verify no regressions

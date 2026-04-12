## Why

The project has pytest-django configured with PostGIS but almost no actual tests — all test files are empty stubs. Before meaningful API and admin tests can be written, we need a test data infrastructure: a way to seed the database with realistic data (huts, geoplaces, organizations, availability) that persists across test runs using `--reuse-db`, with automatic transaction rollback for test isolation.

## What Changes

- Add `factory_boy` dependency for generating model instances with randomized data
- Create management commands (`test_export_huts`, `test_export_geoplaces`) that dump real database records to YAML seed files, with options for random sorting, limiting, and filtering
- Create factory_boy factories for all key models (Hut, GeoPlace, Contact, Owner, Availability) that combine static seed data with randomized fields
- Create a session-scoped pytest fixture that loads seed data from YAML on first run (or `--create-db`), leveraging Django's transaction rollback for per-test isolation
- Create an initial seed file with ~10 huts for immediate use, expandable via the export commands
- Define the test directory structure for API and admin tests

## Capabilities

### New Capabilities

- `test-export-commands`: Management commands to export existing huts and geoplaces from the database as YAML seed files, with options for sorting (random, alpha, elevation), limiting, and output path
- `test-seed-data`: Factory definitions, seed file format, and session-scoped pytest fixture for loading seed data into the test database with `--reuse-db` support
- `test-factories`: factory_boy factory definitions for Hut, GeoPlace, Contact, Owner, Availability and related models, using known coordinates from seed data with randomized attributes

### Modified Capabilities

## Impact

- **Dependencies**: Add `factory_boy` to project dependencies
- **New files**: Management commands in `server/apps/huts/management/commands/` and `server/apps/geometries/management/commands/`, factory definitions in `tests/`, seed YAML files in `tests/seed/`
- **Existing files**: `tests/conftest.py` updated with session-scoped seed fixture, `tests/apps/conftest.py` updated with factory fixtures
- **CI**: No changes needed — the existing `--create-db`/`--reuse-db` flow in GitHub Actions works with this approach (seed runs on cache miss when DB is created fresh)

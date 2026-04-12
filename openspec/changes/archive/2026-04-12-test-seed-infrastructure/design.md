## Context

The project uses pytest-django with PostGIS, `--reuse-db` for speed, and has a CI pipeline that caches the database. Test files exist as stubs across 9 apps but contain no implementation. Migrations load base data (categories, organizations, contact functions, licenses, symbols). The Hut and GeoPlace models require PostGIS geometry fields and have FK dependencies on categories and organizations.

The data import pipeline pulls hut data from external services (SAC, OSM, HRS, Wikidata) via management commands. Real huts exist in the development database but there is no way to export them as portable seed data for tests.

## Goals / Non-Goals

**Goals:**

- Enable fast, deterministic test runs with a pre-seeded PostGIS database
- Provide management commands to export real huts/geoplaces as YAML seed files from any database
- Use factory_boy for generating additional randomized model instances around known coordinates
- Leverage Django's transaction rollback (`pytest.mark.django_db`) for automatic test isolation — no manual cleanup
- Support `--reuse-db` workflow: seed once, run many times
- Start with ~10 huts as initial seed, expandable via export commands to hundreds

**Non-Goals:**

- SQLite test database (PostGIS features require Postgres)
- Testing external service integrations (image processing, availability imports — these are slow tests, separate concern)
- Full test coverage for all apps (this change establishes infrastructure; writing the actual tests is a follow-up)
- Custom test database cleanup/restore logic (Django transaction rollback handles this)

## Decisions

### 1. YAML as seed file format

**Choice**: YAML files in `tests/seed/`
**Alternative**: JSON fixtures, factory_boy-only (no seed files)

YAML is more readable and editable than JSON. Seed files capture real data from the production/dev database via export commands. Factories supplement this with randomized data. The two approaches complement each other: seed files for realistic, deterministic base data; factories for per-test variation.

### 2. Separate export commands per model

**Choice**: `test_export_huts` and `test_export_geoplaces` as separate management commands
**Alternative**: Single `test_export` command with `--model` flag

Separate commands are simpler, each in its own app directory. Huts and geoplaces have different relations, fields, and export logic. No need for a dispatcher.

### 3. Seed loading as session-scoped pytest fixture

**Choice**: A `session`-scoped fixture in `tests/conftest.py` that detects whether seeding is needed
**Alternative**: Custom pytest plugin, management command called in CI

A fixture is idiomatic pytest, runs automatically, and integrates with `--reuse-db`. Detection: if the seed file has changed (hash check) or DB has no huts, re-seed. This handles both first-run and seed-file-updated scenarios.

### 4. Transaction rollback for test isolation

**Choice**: Use `@pytest.mark.django_db` (default transaction mode) which wraps each test in a transaction that rolls back
**Alternative**: `SerializedRollbackTestCase`, manual savepoints, truncate-and-reseed

Default pytest-django behavior is the simplest and fastest. The seeded data, committed before tests run, is visible inside each test's transaction. Any creates/deletes/updates are rolled back automatically. No custom code needed.

### 5. Known coordinates with factory randomization

**Choice**: Seed files contain real coordinates (from export). Factories use these coordinates as anchors and randomize other attributes (capacity, names, contact info, etc.)
**Alternative**: Purely random coordinates, purely deterministic data

Real coordinates make spatial queries testable (nearby, bbox, distance calculations). Randomized attributes provide variety for filter/pagination tests without needing hundreds of hand-crafted records.

## Risks / Trade-offs

- **[PostGIS required]** → All tests need a running PostGIS instance. This is already the case in CI and local development (docker-compose). Not a new risk, just a constraint.
- **[Seed file drift]** → If models change, seed YAML files may become stale → Mitigation: seed files are version-controlled and regeneratable via export commands. Add a seed version/hash check.
- **[Export command depends on real data]** → Export commands need a database with actual huts to export → Mitigation: the initial ~10 hut seed file is committed to the repo, so tests work without any pre-existing data. Export is an enhancement path.
- **[factory_boy as new dependency]** → Adds a test-only dependency → Mitigation: factory_boy is standard in Django testing, well-maintained, minimal overhead.

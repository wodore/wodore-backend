## ADDED Requirements

### Requirement: Seed data loaded from YAML files
The test infrastructure SHALL load seed data from YAML files (`tests/seed/huts.yaml`, `tests/seed/geoplaces.yaml`) into the test database via a session-scoped pytest fixture. The fixture SHALL run once per test session, before any tests execute.

#### Scenario: First run with empty database
- **WHEN** pytest runs with `--create-db` and the database has no huts
- **THEN** the seed fixture loads organizations from fixtures, creates huts from the YAML seed file with all relations (orgs, contacts, categories), and commits the data

#### Scenario: Subsequent run with seeded database
- **WHEN** pytest runs with `--reuse-db` and the database already contains seed data
- **THEN** the seed fixture detects existing data and skips seeding

#### Scenario: Seed file updated
- **WHEN** the seed YAML file content has changed (detected via hash comparison)
- **THEN** existing seed data is cleared and reloaded from the updated file

### Requirement: Transaction rollback test isolation
Each test marked with `@pytest.mark.django_db` SHALL run inside a database transaction that is rolled back after the test completes. Seed data committed before the test session SHALL be visible to all tests.

#### Scenario: Test modifies seed data
- **WHEN** a test deletes a seeded hut and asserts it's gone
- **THEN** the hut is absent during that test
- **AND** the hut is present again in the next test

#### Scenario: Test creates new data
- **WHEN** a test creates a new hut and asserts it exists
- **THEN** the hut exists during that test
- **AND** the hut does not exist in the next test

### Requirement: Seed file format
Seed YAML files SHALL use a structured format with a top-level key matching the model name (e.g., `huts:`, `geoplaces:`), containing a list of records. Each record SHALL include all fields needed to recreate the model instance and its relations.

#### Scenario: Hut seed record
- **WHEN** a hut seed record contains name, location, elevation, country, hut_type_open, organizations, and contacts
- **THEN** the seed loader creates a Hut with those fields, generates the slug on save, and links the specified organizations and contacts

#### Scenario: GeoPlace seed record
- **WHEN** a geoplace seed record contains name, location, elevation, country, and categories
- **THEN** the seed loader creates a GeoPlace with those fields, generates the slug on save, and links the specified categories

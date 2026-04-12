## ADDED Requirements

### Requirement: Export huts as YAML seed file
The `test_export_huts` management command SHALL export hut records from the database to a YAML file, including name, coordinates (SRID=4326 POINT), elevation, country code, hut type slugs (open/closed), capacity (open/closed), organization associations with source IDs, and contact associations.

#### Scenario: Export all huts with default settings
- **WHEN** `test_export_huts` is run without options
- **THEN** all active, public huts are exported to stdout in YAML format

#### Scenario: Export limited number of huts with random sorting
- **WHEN** `test_export_huts --limit 10 --sort random` is run
- **THEN** 10 randomly selected huts are exported

#### Scenario: Export to file
- **WHEN** `test_export_huts --out tests/seed/huts.yaml` is run
- **THEN** YAML output is written to the specified file path

#### Scenario: Export includes organization associations
- **WHEN** a hut has multiple organizations linked (e.g., SAC and HRS)
- **THEN** each organization slug and source_id is included in the hut's export data

#### Scenario: Export includes contact associations
- **WHEN** a hut has contacts
- **THEN** each contact's function slug, name, email, and phone are included

#### Scenario: Export with sorting options
- **WHEN** `test_export_huts --sort alpha` is run
- **THEN** huts are sorted alphabetically by name
- **WHEN** `test_export_huts --sort elevation` is run
- **THEN** huts are sorted by elevation descending

#### Scenario: Export inactive huts
- **WHEN** `test_export_huts --include-inactive` is run
- **THEN** inactive huts are included in the export alongside active ones

### Requirement: Export geoplaces as YAML seed file
The `test_export_geoplaces` management command SHALL export geoplace records from the database to a YAML file, including name, coordinates, elevation, country code, category slugs, importance, and detail type.

#### Scenario: Export all geoplaces with default settings
- **WHEN** `test_export_geoplaces` is run without options
- **THEN** all active, public geoplaces are exported to stdout in YAML format

#### Scenario: Export limited number with random sorting
- **WHEN** `test_export_geoplaces --limit 50 --sort random` is run
- **THEN** 50 randomly selected geoplaces are exported

#### Scenario: Export includes categories
- **WHEN** a geoplace has multiple categories
- **THEN** all category slugs are included in the export data

#### Scenario: Export to file
- **WHEN** `test_export_geoplaces --out tests/seed/geoplaces.yaml` is run
- **THEN** YAML output is written to the specified file path

#### Scenario: Export with sorting options
- **WHEN** `test_export_geoplaces --sort alpha` is run
- **THEN** geoplaces are sorted alphabetically by name
- **WHEN** `test_export_geoplaces --sort elevation` is run
- **THEN** geoplaces are sorted by elevation descending

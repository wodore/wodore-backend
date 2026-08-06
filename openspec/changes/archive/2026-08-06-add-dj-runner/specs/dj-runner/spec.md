## ADDED Requirements

### Requirement: django-q2 integration with ORM backend
The system SHALL configure django-q2 with the ORM broker using the default database connection, enabling task scheduling and async execution without external message brokers.

#### Scenario: django-q2 configuration is present
- **WHEN** the Django settings are loaded
- **THEN** `Q_CLUSTER` SHALL be configured with `orm: "default"` broker and `ADMIN_RUNNER_BACKEND` SHALL be set to `"django-q2"`

#### Scenario: django-q2 models are available in admin
- **WHEN** a staff user accesses the admin interface
- **THEN** Schedule, Success, Failure, and OrmQ models SHALL be registered with Unfold-styled admin classes

### Requirement: Management commands are registered with admin runner
The system SHALL register all 18 management commands with `@register_command`, organized by groups matching their app purpose.

#### Scenario: Commands are registered by group
- **WHEN** the admin runner registry is populated
- **THEN** the following commands SHALL be registered with their respective groups:
  - Availability: `update_availability`
  - Categories: `category_sync_assets`
  - Computed Fields: `updatedata`
  - External Geonames: `import_boundaries`, `import_features`, `import_geonames`, `import_hierarchy`
  - External Links: `check_external_links_health`
  - Geometries: `geoplaces_import_osm`, `import_geoplaces`, `martin_clean_cache`
  - Huts: `hut_sources`, `hut_types`, `huts`, `martin_sync`
  - Licenses: `licenses`
  - Meteo: `import_meteoswiss`, `import_weather_icons`
  - Organizations: `organizations`

#### Scenario: Registered commands remain CLI-compatible
- **WHEN** a registered command is invoked from the command line
- **THEN** it SHALL execute identically to before registration, with no behavioral changes

### Requirement: Schedule admin has command dropdown
The Schedule admin SHALL provide a dropdown for the `func` field populated with registered command entries, replacing the default text input.

#### Scenario: Creating a scheduled task via admin
- **WHEN** a staff user creates a new Schedule entry
- **THEN** the `func` field SHALL display a dropdown listing all registered management commands, with each option using the `django_admin_runner.tasks.execute_command` callable

### Requirement: Unfold sidebar includes command runner navigation
The system SHALL add Command Runner and Scheduled Tasks sections to the Unfold sidebar navigation.

#### Scenario: Admin sidebar shows runner sections
- **WHEN** a staff user views the admin sidebar
- **THEN** navigation items for "Commands", "Results", and Scheduled Tasks (Schedules, Successful tasks, Failed tasks, Queued tasks) SHALL be visible

### Requirement: Packages are installed and apps configured
The system SHALL add `django_q` and `django_admin_runner` to `INSTALLED_APPS` and install the required packages.

#### Scenario: Dependencies are installed
- **WHEN** the project dependencies are installed
- **THEN** `django-q2` and `django-admin-runner` with `django-q2` and `unfold` extras SHALL be available

#### Scenario: Apps are registered
- **WHEN** Django starts
- **THEN** `django_q` and `django_admin_runner` SHALL appear in `INSTALLED_APPS` after `unfold` and `django.contrib.admin`

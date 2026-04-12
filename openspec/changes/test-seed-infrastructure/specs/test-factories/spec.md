## ADDED Requirements

### Requirement: Hut factory with known coordinates
A `HutFactory` SHALL create Hut instances using factory_boy, accepting optional coordinate overrides. By default it SHALL generate a valid hut with a random name, a Point location (SRID 4326) within Switzerland, a category for `hut_type_open`, and default values for all required fields.

#### Scenario: Create hut with default values
- **WHEN** `HutFactory.create()` is called
- **THEN** a Hut is created with a random name, random Swiss coordinates, a valid hut_type_open category, `is_active=True`, `country=CH`, and slug auto-generated on save

#### Scenario: Create hut at specific coordinates
- **WHEN** `HutFactory.create(location=Point(lat=46.02, lon=7.75, srid=4326))` is called
- **THEN** the hut is created at the specified coordinates

#### Scenario: Create hut linked to organizations
- **WHEN** `HutFactory.create(organizations=[org_sac])` is called
- **THEN** the hut is linked to the specified organizations via HutOrganizationAssociation

### Requirement: GeoPlace factory with known coordinates
A `GeoPlaceFactory` SHALL create GeoPlace instances using factory_boy with a valid Point location, at least one category, a random name, and a slug auto-generated on save.

#### Scenario: Create geoplace with default values
- **WHEN** `GeoPlaceFactory.create()` is called
- **THEN** a GeoPlace is created with a random name, random Swiss coordinates, a linked category, `is_active=True`, and slug auto-generated on save

#### Scenario: Create geoplace with specific categories
- **WHEN** `GeoPlaceFactory.create(categories=[cat])` is called
- **THEN** the geoplace is linked to the specified categories

### Requirement: Contact factory
A `ContactFactory` SHALL create Contact instances with a valid ContactFunction, random name, and optional email/phone.

#### Scenario: Create contact with default values
- **WHEN** `ContactFactory.create()` is called
- **THEN** a Contact is created with a random name, linked to an existing ContactFunction (or creates one), and `is_active=True`

### Requirement: Availability factory
An `AvailabilityFactory` SHALL create HutAvailability instances with valid occupancy calculations based on provided `free` and `total` values.

#### Scenario: Create availability record
- **WHEN** `AvailabilityFactory.create(hut=hut, source_organization=org, availability_date=date(2026, 4, 15), free=10, total=50)` is called
- **THEN** an availability record is created with `occupancy_percent=80.0`, correct `occupancy_steps`, and `occupancy_status` derived from the occupancy percentage

#### Scenario: Availability unique constraint
- **WHEN** `AvailabilityFactory.create()` is called twice with the same hut and date
- **THEN** the second call raises an integrity error (hut+date unique constraint)

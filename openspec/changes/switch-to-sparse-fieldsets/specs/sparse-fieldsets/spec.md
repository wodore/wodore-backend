# sparse-fieldsets Specification

## ADDED Requirements

### Requirement: Sparse fieldset query parameter

The API SHALL support a `fields[TYPE]` query parameter on endpoints with
field narrowing, following JSON:API sparse fieldsets semantics.

#### Scenario: Positive selection

- **WHEN** a client sends `GET /v1/huts/{slug}?fields[huts]=slug,name,elevation`
- **THEN** the response contains only `slug`, `name`, `elevation` (plus
  required fields) in the hut object
- **AND** the response status is 200

#### Scenario: Type-scoped nesting

- **WHEN** a response contains nested `sources` objects and the client sends
  `fields[huts]=slug,sources&fields[sources]=slug,name`
- **THEN** the hut object contains `slug` and the full `sources` array, with
  each source narrowed to `slug` and `name`

#### Scenario: Unknown field name

- **WHEN** a client sends `fields[huts]=slug,no_such_field`
- **THEN** the response status is 400
- **AND** the error body lists the valid field names

#### Scenario: Unknown type bracket

- **WHEN** a client sends `fields[no_such_type]=slug` to an endpoint
- **THEN** the response status is 400
- **AND** the error body lists the valid type names for the endpoint

#### Scenario: Full selection keyword

- **WHEN** a client sends `fields[huts]=__all__`
- **THEN** the response contains every field of the DTO, matching the
  endpoint's documented full schema

### Requirement: include/exclude deprecation

The legacy `include`/`exclude` parameters SHALL keep their exact current
behavior while being announced as deprecated.

#### Scenario: Deprecation headers on legacy narrowing

- **WHEN** a client sends `include` or `exclude` to a narrowing endpoint
- **THEN** the response carries `Deprecation` and `Sunset` headers
- **AND** the OpenAPI schema marks both parameters `deprecated: true` with
  the replacement documented

#### Scenario: Pinned old versions keep legacy parameters

- **WHEN** a client pinned to a version registered before the sparse-fieldsets
  version sends `include`/`exclude`
- **THEN** the parameters keep working for that version for as long as the
  version is supported, per the version lifecycle

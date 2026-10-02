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

### Requirement: include/exclude removal

The legacy `include`/`exclude` parameters SHALL be removed together with
the introduction of `fields[TYPE]` (sunset window: 0 — no deprecation
period; no consumer exists).

#### Scenario: Legacy parameters rejected on the new version

- **WHEN** a client sends `include` or `exclude` to a narrowing endpoint
  without pinning an old API version
- **THEN** the response status is 400 with the `invalid_parameter` code
- **AND** the error body names the `fields[TYPE]` replacement

#### Scenario: Pinned old versions keep legacy parameters

- **WHEN** a client pinned to a version registered before this change sends
  `include`/`exclude`
- **THEN** the parameters keep working for that version for as long as the
  version is supported, per the version lifecycle

#### Scenario: New version snapshot documents only fields

- **WHEN** the OpenAPI snapshot of the version introducing this change is
  generated
- **THEN** `include`/`exclude` do not appear as parameters
- **AND** the `fields` parameter is documented with `style: deepObject`

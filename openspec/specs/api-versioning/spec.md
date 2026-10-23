# api-versioning Specification

## Purpose
TBD - created by archiving change add-api-date-versioning. Update Purpose after archive.
## Requirements
### Requirement: Version selection
The API SHALL resolve the requested API version from the `Api-Version` request header, otherwise from the `api_version` query parameter, otherwise default to the latest supported version, and SHALL echo the resolved version in the `Api-Version` response header.

#### Scenario: Header provided
- **WHEN** a client sends `Api-Version: 2026-12-01` to a versioned endpoint
- **THEN** the response is shaped for version `2026-12-01`
- **AND** the response contains `Api-Version: 2026-12-01`

#### Scenario: Query parameter provided
- **WHEN** a client requests `/v1/huts/huts.geojson?api_version=2026-12-01` without the header
- **THEN** the response is shaped for version `2026-12-01`

#### Scenario: No version provided
- **WHEN** a client sends neither header nor query parameter
- **THEN** the latest supported version is served
- **AND** the response `Api-Version` header carries the latest version

#### Scenario: Header and query agree
- **WHEN** header and query parameter specify the same version
- **THEN** the request is served normally for that version

#### Scenario: Conflicting header and query parameter
- **WHEN** header and query parameter specify different versions
- **THEN** the API responds `400` with code `api_version_conflict`

#### Scenario: Unknown version
- **WHEN** a client requests a version not in the registry or not a valid `YYYY-MM-DD` date
- **THEN** the API responds `400` with code `api_version_invalid`

### Requirement: Versioning scope
Versioning SHALL apply to all `/v1/` operations returning a body, including `.geojson` operations, and SHALL NOT apply to explicitly excluded operations: SVG redirects, `/v1/version`, the OpenAPI schema and the docs views.

#### Scenario: GeoJSON endpoint is versioned
- **WHEN** a client requests a `.geojson` operation with a supported old version
- **THEN** the feature properties are transformed to that version

#### Scenario: SVG redirect is not versioned
- **WHEN** a client requests `/v1/symbols/detailed/mountain.svg` with any `Api-Version` value, including an unknown one
- **THEN** the redirect behaves identically for all versions and no version error is raised

### Requirement: Backward transforms
The API SHALL execute only the latest handler logic and SHALL produce older versions by applying registered response downgrade transforms (newest → oldest) for every change newer than the requested version, keyed by OpenAPI operation id.

#### Scenario: Response downgrade
- **WHEN** version `2027-03-01` renamed a field and a client requests `2026-12-01`
- **THEN** the response contains the old field name and not the new one

#### Scenario: Multiple changes chained
- **WHEN** two registered changes exist after the requested version
- **THEN** both downgrades are applied in reverse chronological order

#### Scenario: Field omitted by include/exclude
- **WHEN** a transformed field was excluded via `include`/`exclude` or `include_*=no`
- **THEN** the transform does not fail and does not add the field

#### Scenario: Direct-write GeoJSON endpoints are covered
- **WHEN** the `huts.geojson` or `availability/{date}.geojson` operation has a registered downgrade and the client requests an older version
- **THEN** the feature properties are transformed before serialization

### Requirement: Registry integrity
The system SHALL validate at startup that every operation id referenced by a registered `VersionChange` resolves against the live OpenAPI schema, and SHALL fail startup (system check) otherwise.

#### Scenario: Typo in registry
- **WHEN** a `VersionChange` references an operation id that does not exist in the live schema
- **THEN** the system check fails with a message naming the unknown operation id

#### Scenario: Auto-generated id renamed
- **WHEN** a handler function rename changes its auto-generated operation id that a `VersionChange` references
- **THEN** the system check fails instead of silently skipping the transform

### Requirement: Deprecation and sunset lifecycle for versions
The API SHALL announce deprecated versions via `Deprecation` (RFC 9745), `Sunset` (RFC 8594) and `Link; rel="deprecation"` response headers, and SHALL reject versions past their sunset date with `410`.

#### Scenario: Deprecated version
- **WHEN** a client requests a deprecated version before its sunset date
- **THEN** the response succeeds and contains `Deprecation`, `Sunset` and `Link` headers

#### Scenario: Sunset version
- **WHEN** a client requests a version after its sunset date
- **THEN** the API responds `410` with code `api_version_sunset`

#### Scenario: Minimum deprecation period
- **WHEN** a version is registered as deprecated
- **THEN** its sunset date is at least 6 months after its deprecation

### Requirement: Deprecation lifecycle for endpoints
Endpoints marked deprecated SHALL send `Deprecation` and `Sunset` headers with a concrete sunset date; after that date they SHALL return `410`.

#### Scenario: Bookings endpoint announces sunset
- **WHEN** a client requests `/v1/huts/bookings` or `/v1/huts/bookings.geojson` before their sunset date
- **THEN** the response contains `Deprecation` and `Sunset` headers with the registered sunset date

#### Scenario: Bookings endpoint past sunset
- **WHEN** a client requests `/v1/huts/bookings*` after the sunset date
- **THEN** the API responds `410` with a deprecation notice referencing the replacement endpoint

### Requirement: Version discovery
`GET /v1/version` SHALL additionally return an `api` object with the current version, the default version and all supported versions including status and optional sunset date, without changing existing response fields.

#### Scenario: App checks versions at startup
- **WHEN** a client requests `/v1/version`
- **THEN** the response contains the existing build fields
- **AND** an `api` object with `current`, `default` and a `supported` list of `{version, status, sunset?}` entries

### Requirement: Cross-origin access to version headers
CORS configuration SHALL allow the `Api-Version` request header and expose the `Api-Version`, `Deprecation`, `Sunset` and `Link` response headers to browser clients.

#### Scenario: Browser/WebView client reads headers
- **WHEN** a Capacitor or web client on another origin calls the API
- **THEN** it can send `Api-Version` and read the lifecycle and echo headers

### Requirement: Caching correctness
Responses whose version was resolved from the header SHALL include `Vary: Api-Version`, and cached or conditional responses SHALL NOT mix content across versions.

#### Scenario: CDN caching
- **WHEN** a response is resolved via the `Api-Version` header
- **THEN** the response contains `Vary: Api-Version`

#### Scenario: ETag keyed by version
- **WHEN** the `huts.geojson` ETag is computed
- **THEN** the resolved API version (and a registry content hash) participate in the ETag key material
- **AND** a conditional request for one version cannot produce a `304` reusing another version's representation

### Requirement: Unpinned request observability
Requests without an explicit version SHALL be identifiable in request logs.

#### Scenario: Measuring adoption
- **WHEN** a client calls a versioned endpoint without header or query parameter
- **THEN** the request log carries the fact that no version was pinned (structured field or metric)

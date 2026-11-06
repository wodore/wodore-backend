## ADDED Requirements

### Requirement: Single error contract preserved

Every error response from `/v1/` endpoints SHALL be a single JSON object carrying the machine-readable `code` (a value of the `ErrorCode` registry) and the human-readable `detail`, with the HTTP status communicated by the status line — exactly as before the RFC 9457 enrichment. No existing member, member value or status code SHALL be removed, renamed or re-mapped.

#### Scenario: Not-found error shape

- **WHEN** a client requests a hut slug that does not exist
- **THEN** the response is 404 with a JSON body whose `code` is `"not_found"` and whose `detail` is a human-readable message

#### Scenario: Existing codes unchanged

- **WHEN** any endpoint raises an error that existed before the enrichment (e.g. `validation_error`, `throttled`, `not_authenticated`, `insufficient_permission`, `gone`, `service_unavailable`)
- **THEN** the response's `code` and `detail` values are byte-identical in semantics to the pre-enrichment contract, with no field removals or renames

### Requirement: RFC 9457 problem members derived from the ErrorCode registry

Every error response SHALL additionally include the RFC 9457 members `type`, `title` and `status`: `type` SHALL be the stable URI registered for the raised code (`https://hub.wodore.com/errors/<snake_case_code>` form, from API-origin settings), `title` SHALL be the code's registered human summary, and `status` SHALL mirror the response's HTTP status code as an integer. The `instance` member (URI of the affected resource) SHALL be included only where a resource path is identifiable, and omitted otherwise. The `code` member remains a registered RFC 9457 extension member.

#### Scenario: Validation error shape

- **WHEN** a client sends an invalid query parameter to any dmr controller
- **THEN** the response is 400 with a body containing `code` `"validation_error"`, the joined human `detail`, `type` `https://hub.wodore.com/errors/validation_error`, `title` of the code's human summary, and `status` `400`

#### Scenario: Enriched not-found carries instance

- **WHEN** a client requests a non-existent hut detail resource path
- **THEN** the 404 body additionally carries `instance` identifying the requested resource path

#### Scenario: Errors without an affected resource omit instance

- **WHEN** an error has no identifiable resource path (e.g. throttled, authentication or version-resolution failures)
- **THEN** the body omits `instance` entirely rather than asserting an unrelated URI

#### Scenario: Registry completeness

- **WHEN** a new `ErrorCode` member is added to the registry
- **THEN** it SHALL declare its human `title` and stable `type` URI in the same registry, and a unit test SHALL fail if any registered code lacks them

### Requirement: Shared machinery inheritance across all serving surfaces

The RFC 9457 enrichment SHALL be implemented once in the shared error machinery (`ApiController` error formatting/handling, the `raise_not_found`/dmr `APIError` response-writing path, and the API-version middleware's error responses), such that every dmr controller, plain Django view and GeoJSON endpoint produces the enriched error body without per-endpoint work.

#### Scenario: GeoJSON endpoint inheritance

- **WHEN** a direct-write GeoJSON endpoint raises `raise_not_found`
- **THEN** the error response body carries `code`/`detail` plus the RFC 9457 members, identical in shape to a dmr controller's error

#### Scenario: Version middleware errors enriched

- **WHEN** a request carries conflicting `Api-Version` header and `api_version` query values, or names an unknown version
- **THEN** the middleware's 400 error body carries `code`/`detail` plus `type`, `title` and `status`, with `instance` omitted

#### Scenario: Throttled responses keep the standard contract plus problem members

- **WHEN** any throttled endpoint rejects a request
- **THEN** the 429 body still has `code` `"throttled"` and a human `detail` (with `Retry-After`/`X-RateLimit-*` headers unchanged) and additionally carries `type`, `title` and `status` `429`

### Requirement: Pinned-version clients receive enriched error bodies

Error-body enrichment SHALL apply to all API versions, including clients pinned to older versions; no version transform SHALL strip the RFC 9457 members, and no new API version SHALL be created for this change. The OpenAPI error schema SHALL document the optional problem members on the error model.

#### Scenario: Pinned-version client sees additive fields

- **WHEN** a client pinned to a released version receives any error response
- **THEN** the body contains the same `code`/`detail` as before the enrichment, plus the RFC 9457 members, with no member removed or reshaped relative to the pre-enrichment contract

#### Scenario: OpenAPI error schema documents the shape

- **WHEN** the OpenAPI schema is generated or snapshotted
- **THEN** the error model documents `code` and `detail` plus optional `type`, `title`, `status` and `instance`

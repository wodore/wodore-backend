## ADDED Requirements

### Requirement: Gated public endpoints require an active client key

Requests to the gated public surface — `/v1/huts/*`, `/v1/geo/*` (including
`/v1/geo/images/*`), and `POST /v1/feedback/` — MUST present an active
client key in the `X-Client-Key` header. The key MUST be validated by hash
lookup against the key registry; no plaintext keys are ever stored. Invalid,
unknown, and revoked keys MUST be indistinguishable in the response. CORS
preflight (`OPTIONS`) requests MUST NOT be gated.

#### Scenario: Valid key grants access

- **WHEN** a request hits `GET /v1/huts/huts` with the `X-Client-Key` header
  of an active key
- **THEN** the request is processed normally and responds `200`

#### Scenario: Missing key is rejected

- **WHEN** a request hits a gated endpoint without an `X-Client-Key` header
- **THEN** the API responds `403` and does not execute the operation

#### Scenario: Revoked key is rejected

- **WHEN** a key's registry entry is deactivated and a request presents it
- **THEN** the API responds `403` as if the key were unknown

### Requirement: Foreign browser origins are rejected on gated endpoints

When an `Origin` or `Referer` header is present on a gated request, its
host MUST be in the trusted frontend origins (derived from
`DJANGO_TRUSTED_DOMAINS`); otherwise the request MUST be rejected with
`403` regardless of key validity. Requests without an `Origin`/`Referer`
header (native apps, server-side tools) MUST pass this layer on key
strength alone.

#### Scenario: Trusted origin with valid key

- **WHEN** a gated request carries `Origin: https://www.wodore.ch` and a
  valid key
- **THEN** the request is processed normally

#### Scenario: Foreign origin is rejected even with a valid key

- **WHEN** a gated request carries `Origin: https://evil.example` and a
  valid key
- **THEN** the API responds `403`

#### Scenario: Non-browser caller without origin headers

- **WHEN** a gated request has neither `Origin` nor `Referer` and presents
  a valid key
- **THEN** the request is processed normally

### Requirement: Per-key rate limiting on gated endpoints

Each client key MUST have a request budget (fixed window, cache-backed
counter) across the gated endpoints. Exceeding the budget MUST respond
`429` with a `Retry-After` header; the counter MUST reset in the next
window. Requests rejected by rate limiting MUST NOT execute the operation.

#### Scenario: Budget exhaustion

- **WHEN** a key exceeds its window budget on gated endpoints
- **THEN** further gated requests in that window respond `429` and include
  `Retry-After`

#### Scenario: Window reset

- **WHEN** the rate-limit window has elapsed since exhaustion
- **THEN** requests with the same key are processed again

### Requirement: Gate kill-switch

The gate MUST be disableable at runtime via the `CLIENT_VERIFY_ENABLED`
environment flag without code changes. With the flag off, gated endpoints
MUST behave exactly as before this change (fully public, no key, no origin
check, no rate limit). The flag MUST default to enabled in production and
staging, disabled in development and test.

#### Scenario: Kill-switch off restores public behavior

- **WHEN** `CLIENT_VERIFY_ENABLED=false` and a gated endpoint is called
  without any key or origin headers
- **THEN** the request is processed normally

#### Scenario: Default is enforcing in production

- **WHEN** production starts without an explicit `CLIENT_VERIFY_ENABLED`
- **THEN** the gate is active

### Requirement: Write endpoints require bearer authentication

The mutations that are public today — organizations `POST`, `PUT`,
`DELETE` and symbols `POST` — MUST require a valid bearer token via the
existing API token validation. Unauthenticated mutation attempts MUST
respond `401`.

#### Scenario: Anonymous organization write is rejected

- **WHEN** `POST /v1/organizations/` is called without a bearer token
- **THEN** the API responds `401` and creates nothing

#### Scenario: Token-authenticated write succeeds

- **WHEN** the same call carries a valid access token with sufficient
  permissions
- **THEN** the mutation is processed as before

### Requirement: Ungated endpoints remain public

Static, cacheable asset and metadata endpoints — `/v1/symbols/*`,
`/v1/categories/*`, `/v1/meteo/*`, `/v1/version` — MUST NOT require a
client key, origin, or rate-limit check.

#### Scenario: Asset endpoint without key or origin

- **WHEN** `GET /v1/symbols/` is called with no `X-Client-Key` and no
  `Origin`
- **THEN** the request is processed normally

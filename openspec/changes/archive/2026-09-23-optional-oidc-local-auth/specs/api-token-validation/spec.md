## ADDED Requirements

### Requirement: Validator routing by auth mode
The `AuthBearer` security class SHALL select its token validator from settings at
instantiation: the Zitadel introspection validator when `OIDC_ENABLED` is true, a
local JWT validator when `LOCAL_AUTH_ENABLED` is true, and neither (all
protected endpoints fail) otherwise. Both modes SHALL NOT be active on the same
`AuthBearer` instance.

#### Scenario: Zitadel mode unchanged
- **WHEN** `OIDC_ENABLED=true` and a protected endpoint receives a Zitadel access token
- **THEN** the token is verified via introspection exactly as before this change

#### Scenario: Local mode verification
- **WHEN** `LOCAL_AUTH_ENABLED=true` and a protected endpoint receives a local provider access token
- **THEN** the token's RS256 signature is verified against the local JWKS, expiry is checked, and the request authenticates as the token's `sub` user

### Requirement: Clean 401 when auth is not configured
Protected endpoints SHALL respond with HTTP 401 and a JSON error body stating
that authentication is not configured when neither `OIDC_ENABLED` nor
`LOCAL_AUTH_ENABLED` is true, and SHALL NOT raise an unhandled exception (for
example from missing `OIDC_OP_INTROSPECTION_ENDPOINT`).

#### Scenario: Disabled mode request
- **WHEN** both flags are false and a protected endpoint is called with any Authorization header
- **THEN** the response is 401 with a descriptive JSON error and no 500 occurs

### Requirement: Shared scope, role, and group matching
Scope, role, and group matching SHALL be implemented once in a shared validator
base (`match_token_scopes`, `match_token_roles`, `match_token_groups`, token
validation errors) and reused by both validators, preserving current semantics:
non-`group:`-prefixed entries are roles, `group:`-prefixed entries are groups,
and `None` requirements always pass.

#### Scenario: Local token passes role check
- **WHEN** a local token carries roles `perm:bookings` and the endpoint requires `roles=["perm:bookings"]`
- **THEN** authentication succeeds

#### Scenario: Local token fails group check
- **WHEN** a local token's groups are `["editor"]` and the endpoint requires `groups=["admin"]`
- **THEN** the endpoint responds 401 with the insufficient-role/group error body

### Requirement: Protected endpoints are testable in local mode
The test suite SHALL exercise at least one `AuthBearer`-protected endpoint end to
end in local mode: obtain a token via the local provider password grant, call the
protected endpoint, and assert both the success and the 401 denial paths.

#### Scenario: Integration test
- **WHEN** the test suite runs with local auth enabled
- **THEN** a token from `POST /oauth/local/token` authenticates successfully against a protected endpoint, and an invalid token yields 401

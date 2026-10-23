## MODIFIED Requirements

### Requirement: Validator routing by auth mode
The `AuthBearer` security class SHALL verify tokens by issuer, selected from
settings at instantiation: access tokens issued by the built-in OIDC provider
 SHALL be verified locally (signature against the provider JWKS, plus `iss`,
`aud`, and expiry checks) whenever `OIDC_ENABLED` is true; tokens from a legacy
external issuer (Zitadel) SHALL additionally be accepted via introspection
only while the migration flag is active. When `OIDC_ENABLED` is false, no
validator is selected (protected endpoints fail with 401).

#### Scenario: Built-in provider token verified locally
- **WHEN** `OIDC_ENABLED=true` and a protected endpoint receives an access token from the built-in provider
- **THEN** the token's RS256 signature is verified locally against the JWKS, `iss`/`aud`/expiry are checked, and the request authenticates as the token's `sub` user without any network call to an external service

#### Scenario: Legacy issuer accepted during migration
- **WHEN** the migration flag is active and a protected endpoint receives a Zitadel access token
- **THEN** the token is verified via introspection as before, and remains accepted until the flag is removed

#### Scenario: Unknown issuer rejected
- **WHEN** a protected endpoint receives a JWT whose `iss` is neither accepted issuer
- **THEN** the response is 401 and no validator attempts verification of the token

### Requirement: Shared scope, role, and group matching
Scope, role, and group matching SHALL be implemented once in a shared validator
base (`match_token_scopes`, `match_token_roles`, `match_token_groups`, token
validation errors) and reused by all validators, preserving current semantics:
non-`group:`-prefixed entries are roles, `group:`-prefixed entries are groups,
and `None` requirements always pass. Roles SHALL be read from the plain
`roles` claim of built-in provider tokens; while the migration flag is active,
the legacy Zitadel claim keys SHALL still be consulted for external tokens.

#### Scenario: Provider token passes role check
- **WHEN** a built-in provider token carries `roles` including `perm:bookings` and the endpoint requires `roles=["perm:bookings"]`
- **THEN** authentication succeeds

#### Scenario: Provider token fails group check
- **WHEN** a built-in provider token's groups are `["editor"]` and the endpoint requires `groups=["admin"]`
- **THEN** the endpoint responds 401 with the insufficient-role/group error body

### Requirement: Protected endpoints are testable in local mode
The test suite SHALL exercise at least one `AuthBearer`-protected endpoint end to
end against the built-in provider: obtain a token, call the protected endpoint,
and assert both the success and the 401 denial paths.

#### Scenario: Integration test
- **WHEN** the test suite runs with the built-in provider enabled
- **THEN** a token from the provider authenticates successfully against a protected endpoint, and an invalid or wrong-issuer token yields 401

## ADDED Requirements

### Requirement: Local JWT verification without per-request network calls
Verification of built-in provider tokens SHALL NOT perform a network
request per API call: opaque DOT access tokens verify via a local database
lookup (with roles sourced live from the user's Django groups and
revocation taking effect immediately), and JWT-shaped tokens verify locally
via signature, expiry and exact issuer matching (request-derived plus
configured issuer URLs - never by path suffix).

#### Scenario: No network roundtrip
- **WHEN** two consecutive protected requests present the same valid provider token
- **THEN** both succeed with no HTTP request to any external service

#### Scenario: Revocation is immediate
- **WHEN** a valid access token's database row is deleted
- **THEN** the next request presenting it responds 401

#### Scenario: Wrong-issuer JWT rejected
- **WHEN** a properly signed JWT carries an issuer outside the accepted set (e.g. a different host under the same path)
- **THEN** the response is 401

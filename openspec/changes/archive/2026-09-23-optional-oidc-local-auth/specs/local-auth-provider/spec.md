## ADDED Requirements

### Requirement: Local provider activation gate
The system SHALL provide a `LOCAL_AUTH_ENABLED` setting, defaulting to
`(DEBUG or DJANGO_ENV == "test") and not OIDC_ENABLED`, and SHALL raise
`ImproperlyConfigured` during settings import when `LOCAL_AUTH_ENABLED` is true
while `DEBUG` is false and `DJANGO_ENV` is not `test`.

#### Scenario: Default in development
- **WHEN** settings load in development with `OIDC_ENABLED` unset
- **THEN** `LOCAL_AUTH_ENABLED` is true and the local provider routes are active

#### Scenario: Production override refused
- **WHEN** the environment sets `LOCAL_AUTH_ENABLED=true` in production settings
- **THEN** startup aborts with `ImproperlyConfigured`

#### Scenario: Disabled alongside Zitadel
- **WHEN** `OIDC_ENABLED=true` and `LOCAL_AUTH_ENABLED` is unset
- **THEN** `LOCAL_AUTH_ENABLED` is false

### Requirement: OIDC discovery document
When enabled, the local provider SHALL serve
`GET /oauth/local/.well-known/openid-configuration` with the issuer
`{request scheme/host}/oauth/local`, and SHALL include `authorization_endpoint`,
`token_endpoint`, `userinfo_endpoint`, `jwks_uri`, `end_session_endpoint`,
`response_types_supported` containing `code`, `code_challenge_methods_supported`
containing `S256`, and `prompt_values_supported` containing `none`. The provider
SHALL accept any requested scope, including Zitadel-specific URN scopes.

#### Scenario: Frontend-compatible discovery
- **WHEN** an OIDC client fetches the discovery document in local mode
- **THEN** the response is valid JSON listing all endpoints above and `issuer` matches the local provider base URL

### Requirement: Authorization code flow with PKCE
The local provider SHALL implement `GET /oauth/local/authorize` supporting the
authorization-code flow with PKCE (S256 only). When the requester has no
authenticated Django session and the request lacks `prompt=none`, the provider
SHALL render a login form; after successful login it SHALL redirect to the
client's `redirect_uri` with a single-use authorization code valid for at most
60 seconds. When the request includes `prompt=none` and a valid session exists,
the provider SHALL redirect immediately with a code; without a session it SHALL
redirect with `error=login_required`.

#### Scenario: Popup sign-in
- **WHEN** an unauthenticated user opens `/oauth/local/authorize` with valid `client_id`, `redirect_uri`, `response_type=code`, and `code_challenge`
- **THEN** a login form is served and a correct login yields a redirect to `redirect_uri` carrying `code` and `state`

#### Scenario: Silent renew
- **WHEN** `/oauth/local/authorize` is called with `prompt=none` from a frame holding an authenticated session cookie
- **THEN** the provider responds with an immediate redirect containing a fresh authorization code

#### Scenario: Code is single-use
- **WHEN** an authorization code is exchanged at the token endpoint twice
- **THEN** the second exchange fails with `invalid_grant`

### Requirement: Token issuance
The local provider SHALL implement `POST /oauth/local/token` supporting
`grant_type=authorization_code` with mandatory PKCE S256 verification, and
`grant_type=password` for dev/test convenience. Issued access tokens and ID
tokens SHALL be RS256 JWTs signed with the local dev key; the ID token SHALL
contain `sub`, `email`, `name`, and the roles claim.

#### Scenario: Code exchange
- **WHEN** a valid authorization code with the correct `code_verifier` is exchanged
- **THEN** the response contains `access_token`, `id_token`, `token_type=Bearer`, and `expires_in`

#### Scenario: Password grant
- **WHEN** the token endpoint receives valid local username and password
- **THEN** the response contains an `access_token` for that user

### Requirement: Zitadel-shaped userinfo claims
The local provider SHALL implement `GET /oauth/local/userinfo` requiring a valid
local access token, returning `sub`, `email`, `name`, `picture`, and the claim
`urn:zitadel:iam:org:project:roles` as a JSON object whose keys are the user's
Django group names.

#### Scenario: Frontend reads roles
- **WHEN** a user in Django groups `admin` and `editor` authenticates through the local provider and the client calls userinfo
- **THEN** the response contains `"urn:zitadel:iam:org:project:roles": {"admin": {}, "editor": {}}`

### Requirement: JWKS and end-session endpoints
The local provider SHALL serve `GET /oauth/local/jwks` exposing the public key
for its dev keypair, and `GET /oauth/local/end_session` which clears the Django
session and redirects to the `post_logout_redirect_uri` parameter.

#### Scenario: Token signature verification
- **WHEN** a JWT issued by the local provider is validated against the served JWKS
- **THEN** the signature verifies

#### Scenario: Logout
- **WHEN** an authenticated user hits `end_session` with a `post_logout_redirect_uri`
- **THEN** the session is cleared and the response redirects to that URI

### Requirement: Local users bootstrap command
The system SHALL provide a management command creating the local fixture users
(including passwords and Django groups) used by the local provider, idempotent
across repeated runs.

#### Scenario: Idempotent bootstrap
- **WHEN** the command runs twice
- **THEN** users and groups exist exactly once with the configured passwords and memberships

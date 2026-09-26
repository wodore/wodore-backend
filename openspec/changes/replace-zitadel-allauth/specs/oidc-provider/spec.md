## ADDED Requirements

### Requirement: OIDC provider endpoint surface
When `OIDC_ENABLED` is true, the system SHALL serve an OpenID Connect provider
via django-oauth-toolkit: a discovery document
(`.well-known/openid-configuration`), authorization endpoint supporting the
code flow, token endpoint, userinfo endpoint, and JWKS endpoint — all under a
single configurable base path on the backend origin.

#### Scenario: Discovery document
- **WHEN** an OIDC client fetches the discovery document while the provider is enabled
- **THEN** the response is valid JSON with `issuer`, `authorization_endpoint`, `token_endpoint`, `userinfo_endpoint`, and `jwks_uri`, and advertises `code` in `response_types_supported` and `S256` in `code_challenge_methods_supported`

#### Scenario: Authorization code flow end to end
- **WHEN** the SPA redirects to the authorization endpoint with valid `client_id`, `redirect_uri`, `response_type=code`, `code_challenge`, and `state`, and the user has an authenticated session
- **THEN** the response redirects to `redirect_uri` carrying a single-use `code` and the original `state`

### Requirement: Public PKCE clients
The provider SHALL support public clients (no client secret) for the SPA and a
future native Android app. PKCE (S256) SHALL be mandatory for all
authorization-code grants; `redirect_uri` values SHALL match exactly, be
limited to `https` plus explicitly allowlisted private-use app schemes, and
wildcard redirect URIs SHALL be rejected.

#### Scenario: Token request without PKCE is refused
- **WHEN** a code exchange arrives at the token endpoint without `code_verifier`
- **THEN** the request fails with an OAuth error and no tokens are issued

#### Scenario: Mismatched redirect URI is refused
- **WHEN** an authorization request carries a `redirect_uri` that is not an exact registered value
- **THEN** the request is rejected and no code is issued

### Requirement: JWT access tokens with roles claim
Access tokens SHALL be RS256 JWTs containing `iss`, `sub`, `aud`, `exp`, and
scope claims, plus a plain `roles` claim built from the user's Django group
memberships, where `group:`-prefixed entries denote groups and all other
entries denote roles. The userinfo endpoint SHALL return `sub`, `email`,
`name`, and the same `roles` claim for a valid access token.

#### Scenario: Roles reflect Django groups
- **WHEN** a user in Django groups `admin` and `editor` obtains an access token
- **THEN** the token's `roles` claim contains entries for `admin` and `editor`, and userinfo returns the same entries

#### Scenario: Group check still authorizes
- **WHEN** a token issued to a member of `editor` is used on an endpoint requiring `groups=["editor"]`
- **THEN** authorization succeeds using the `group:`-prefixed entries derived from the `roles` claim

### Requirement: Refresh token rotation and reuse protection
The provider SHALL rotate refresh tokens on every use and apply reuse
protection: presenting an already-rotated refresh token SHALL invalidate the
entire token chain for that grant.

#### Scenario: Refresh works and rotates
- **WHEN** a valid refresh token is exchanged at the token endpoint
- **THEN** a new access token and a new refresh token are returned, and the presented refresh token is no longer accepted

#### Scenario: Replay kills the chain
- **WHEN** a previously used refresh token is presented again
- **THEN** the request is rejected and the subsequently issued tokens from that chain are also rejected

### Requirement: Signing key management
The provider's RS256 signing key SHALL be sourced from settings (backed by
Infisical), never committed to the repository. Startup SHALL fail fast with
`ImproperlyConfigured` when the provider is enabled but no signing key is
configured. The JWKS endpoint SHALL publish the public key(s), and key
rotation SHALL be supported by accepting multiple key ids.

#### Scenario: Missing key aborts startup
- **WHEN** the provider is enabled and the signing key setting is empty
- **THEN** startup aborts with `ImproperlyConfigured` naming the missing setting

#### Scenario: JWKS verifies issued tokens
- **WHEN** a JWT issued by the provider is validated against the served JWKS
- **THEN** the signature verifies

### Requirement: Hardened provider defaults
The provider SHALL enforce PKCE for all authorization-code grants,
refresh-token rotation with reuse protection, authorization-code expiry of
at most 60 seconds, exact-match redirect URIs limited to `https` (plus an
allowlisted app scheme for the future Android client; `http` only in
development/test), and the Django system checks SHALL report no
`oauth2_provider` error-level findings in the deployment configuration.
The resource-owner password grant is deliberately kept for development/test
convenience via a dedicated client that is only seeded in those
environments; production has no such client.

#### Scenario: Deployment checks pass
- **WHEN** system checks run with the provider enabled and production settings
- **THEN** no `oauth2_provider` error-level findings are reported

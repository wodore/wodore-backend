## REMOVED Requirements

### Requirement: Local provider activation gate
**Reason**: The dedicated dev/test auth provider app (`server.apps.local_auth`)
is superseded by the built-in OIDC provider (django-oauth-toolkit), which
serves all environments; the separate `LOCAL_AUTH_ENABLED` flag and its
hard guard are no longer needed.
**Migration**: `OIDC_ENABLED` now defaults to true in development and test
(the built-in provider replaces the local one); tests that need auth disabled
set `OIDC_ENABLED=false` explicitly.

### Requirement: OIDC discovery document
**Reason**: The hand-rolled discovery endpoint is replaced by the
django-oauth-toolkit OIDC endpoints.
**Migration**: Use the built-in provider's discovery document (see the
`oidc-provider` capability, "OIDC provider endpoint surface").

### Requirement: Authorization code flow with PKCE
**Reason**: The hand-rolled authorization endpoint (login form, single-use
codes, `prompt=none` silent renew) is replaced by the django-oauth-toolkit
flow, which uses the unified allauth login.
**Migration**: SPA clients use the built-in provider's authorization endpoint
with PKCE S256, exactly as before; login happens through the account
management flow instead of the provider-local form.

### Requirement: Token issuance
**Reason**: The hand-rolled token endpoint (authorization-code + password
grant, RS256 JWTs) is replaced by the django-oauth-toolkit token endpoint.
**Migration**: Clients call the built-in provider's token endpoint; dev/test
scripts use the fixture users with the account login or the dev token
command instead of the password grant.

### Requirement: Zitadel-shaped userinfo claims
**Reason**: The `urn:zitadel:iam:org:project:roles` claim shape is dropped
together with Zitadel; roles come from Django groups via a plain `roles`
claim.
**Migration**: See the `oidc-provider` capability, "JWT access tokens with
roles claim".

### Requirement: JWKS and end-session endpoints
**Reason**: Replaced by the django-oauth-toolkit JWKS endpoint and allauth
logout; the hand-rolled versions are deleted.
**Migration**: Token verification uses the built-in provider's JWKS; logout
uses the account management flow.

### Requirement: Local users bootstrap command
**Reason**: The command is tied to the removed local provider app; fixture
users are still needed for development.
**Migration**: A successor idempotent fixture-user command is specified in
the `account-management` capability ("Dev fixture users command").

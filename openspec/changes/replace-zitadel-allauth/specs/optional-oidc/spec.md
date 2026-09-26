## MODIFIED Requirements

### Requirement: OIDC feature flag
The system SHALL provide an `OIDC_ENABLED` boolean setting sourced from the
`OIDC_ENABLED` environment variable, defaulting to true in all environments
(production, staging, development, and test), with an explicit environment
value always taking precedence. When true, the built-in OIDC provider and
account surfaces are active.

#### Scenario: Default in production
- **WHEN** settings load in production or staging and `OIDC_ENABLED` is unset
- **THEN** `OIDC_ENABLED` is `True`

#### Scenario: Default in development
- **WHEN** settings load in development or test and `OIDC_ENABLED` is unset
- **THEN** `OIDC_ENABLED` is `True` (the built-in provider serves dev/test, replacing the removed local auth provider)

#### Scenario: Explicit override
- **WHEN** the environment sets `OIDC_ENABLED=false` in any environment
- **THEN** `OIDC_ENABLED` is `False` and provider routes are not mounted

### Requirement: api_test_token guards disabled mode
The `api_test_token` management command SHALL mint a token through the active
auth configuration and SHALL exit with a clear error message when
`OIDC_ENABLED` is false.

#### Scenario: Command refuses without the provider
- **WHEN** `api_test_token` runs with `OIDC_ENABLED=false`
- **THEN** the command exits non-zero with a message stating the provider is disabled

#### Scenario: Command issues a usable token
- **WHEN** `api_test_token` runs with `OIDC_ENABLED=true`
- **THEN** the command outputs an access token that authenticates against a protected endpoint

## ADDED Requirements

### Requirement: Provider surface is conditional
When `OIDC_ENABLED` is false, the system SHALL NOT mount the provider or
account URLs, the admin login SHALL fall back to the standard Django login
form, and settings import SHALL NOT require any external network request.

#### Scenario: Admin falls back to Django login
- **WHEN** `OIDC_ENABLED` is false and an anonymous user requests `/admin/`
- **THEN** the response redirects to the standard Django admin login form and no provider route resolves

#### Scenario: No network at import time
- **WHEN** `OIDC_ENABLED` is false and any management command starts
- **THEN** settings import completes without any HTTP request

## REMOVED Requirements

### Requirement: Zitadel RP surface is conditional
**Reason**: The Zitadel relying-party integration (mozilla-django-oidc URLs,
admin redirect to `/oidc/authenticate/`, OIDC PermissionBackend,
SessionRefresh) is removed together with Zitadel; the provider is now built
in.
**Migration**: The conditional-surface behavior for the built-in provider is
covered by the new "Provider surface is conditional" requirement; no
`/oidc/` routes exist anymore at all.

### Requirement: Fail-fast when OIDC is enabled but unreachable
**Reason**: There is no external OIDC provider to reach at startup anymore;
the built-in provider's fail-fast condition is a missing signing key.
**Migration**: Startup validation is covered by the "Signing key management"
requirement in the `oidc-provider` capability.

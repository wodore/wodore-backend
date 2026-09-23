## ADDED Requirements

### Requirement: OIDC feature flag
The system SHALL provide an `OIDC_ENABLED` boolean setting sourced from the
`OIDC_ENABLED` environment variable, defaulting to `not (DEBUG or DJANGO_ENV == "test")`,
with an explicit environment value always taking precedence.

#### Scenario: Default in production
- **WHEN** settings load in production or staging (`DEBUG=False`, `DJANGO_ENV` not `test`) and `OIDC_ENABLED` is unset
- **THEN** `OIDC_ENABLED` is `True`

#### Scenario: Default in development
- **WHEN** settings load in development (`DEBUG=True`) and `OIDC_ENABLED` is unset
- **THEN** `OIDC_ENABLED` is `False`

#### Scenario: Explicit override
- **WHEN** the environment sets `OIDC_ENABLED=true` in development
- **THEN** `OIDC_ENABLED` is `True` regardless of the computed default

### Requirement: Zitadel RP surface is conditional
When `OIDC_ENABLED` is false, the system SHALL NOT mount the `mozilla_django_oidc`
URLs or the `admin/login/` redirect to `/oidc/authenticate/`, SHALL NOT register
the OIDC `PermissionBackend` in `AUTHENTICATION_BACKENDS`, SHALL NOT add the
`SessionRefresh` middleware, and SHALL NOT perform the OIDC discovery network
request during settings import.

#### Scenario: Admin falls back to Django login
- **WHEN** `OIDC_ENABLED` is false and an anonymous user requests `/admin/`
- **THEN** the response redirects to the standard Django admin login form and no `/oidc/` route resolves

#### Scenario: No network at import time
- **WHEN** `OIDC_ENABLED` is false and any management command starts
- **THEN** settings import completes without any HTTP request to the OIDC provider

### Requirement: Fail-fast when OIDC is enabled but unreachable
The system MUST abort startup with `ImproperlyConfigured` when `OIDC_ENABLED` is
true and the OIDC discovery document cannot be retrieved.

#### Scenario: Provider down at boot
- **WHEN** `OIDC_ENABLED` is true and `{OIDC_OP_BASE_URL}/.well-known/openid-configuration` returns a non-200 status or the connection fails
- **THEN** startup aborts with `ImproperlyConfigured` naming the discovery URL

### Requirement: api_test_token guards disabled mode
The `api_test_token` management command SHALL exit with a clear error message
when `OIDC_ENABLED` is false.

#### Scenario: Command refuses without OIDC
- **WHEN** `api_test_token` runs with `OIDC_ENABLED=false`
- **THEN** the command exits non-zero with a message stating OIDC is disabled

### Requirement: OIDC file naming
The settings component and permission backend SHALL use the corrected module
names `server/settings/components/oidc.py` and `server/core/oidc_permission.py`;
no source file SHALL import from the misspelled `oicd` modules afterwards.

#### Scenario: Rename complete
- **WHEN** the codebase is searched for `components.oicd` or `oicd_permission` imports after the change
- **THEN** no references remain outside git history

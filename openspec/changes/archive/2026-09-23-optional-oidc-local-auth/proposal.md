## Why

The backend currently hard-couples to a running Zitadel: settings import fetches the
OIDC discovery document over the network (silently degrading on failure), the admin
login redirects into a broken OIDC view when the IdP is down, and the frontend can
only authenticate through Zitadel. When the local Zitadel stack is unavailable
(recent case: node disk-pressure took it down), local development, admin access and
frontend dev all degrade. We need Zitadel to be **optional for dev and test** while
staying the sole provider in production — and the frontend should run against
Django directly in local mode, ideally by changing only its env vars.

## What Changes

- **Optional OIDC (Zitadel RP)**: new `OIDC_ENABLED` setting (env-overridable;
  default: enabled unless `DEBUG` or `DJANGO_ENV=test`). When disabled: no discovery
  fetch at settings import, no `/oidc/` URLs, no `admin/login/` redirect hack
  (admin falls back to Django's classic login), no `PermissionBackend` in
  `AUTHENTICATION_BACKENDS`, no `SessionRefresh` middleware.
- **Fail-fast when enabled**: if OIDC is enabled but discovery fails, startup raises
  `ImproperlyConfigured` instead of silently producing a broken admin login.
- **Local dev/test auth provider**: a minimal built-in OIDC provider (dev/test only)
  exposing discovery, authorize (PKCE, popup + silent renew), token, userinfo, JWKS
  and `end_session_endpoint` under `/oauth/local/`. It issues JWT access/ID tokens
  signed with a local dev key and emits Zitadel-shaped claims
  (`urn:zitadel:iam:org:project:roles` built from Django groups) so the frontend
  works **with env-var changes only**. Guarded: refuses to activate outside
  DEBUG/test environments.
- **API token validation routing**: `AuthBearer` picks its validator by mode —
  Zitadel introspection (unchanged) when OIDC is enabled, local JWT verification in
  local mode, clean 401 when neither is configured. Role/group matching logic is
  shared. Protected endpoints become testable.
- **Local users bootstrap**: management command to create dev/test users with
  groups/passwords for the local provider.
- **Typo cleanup**: rename `components/oicd.py` → `oidc.py` and
  `core/oicd_permission.py` → `oidc_permission.py` (import/reference updates only).

## Capabilities

### New Capabilities
- `optional-oidc`: `OIDC_ENABLED` flag semantics; conditional Zitadel RP wiring
  (URLs, middleware, auth backends, discovery); fail-fast on enabled-but-unreachable.
- `local-auth-provider`: dev/test-only built-in OIDC provider (PKCE authorization
  code flow, token issuance, userinfo with Zitadel-shaped role claims, session
  handling for popup/silent renew, end-session, password grant for tests).
- `api-token-validation`: bearer token validation routing for Django Ninja
  endpoints (Zitadel introspection vs local JWT vs disabled), role/group/scope
  matching, and behavior when auth is not configured.

### Modified Capabilities

(none — `dj-runner` spec is unaffected)

## Impact

- **Backend settings**: `server/settings/components/oicd.py` (rename + flag),
  `server/settings/__init__.py` (load order), `environments/*.py`
  (SessionRefresh guards), `components/common.py` (AUTHENTICATION_BACKENDS).
- **URLs**: `server/urls.py` (conditional `/oidc/` + admin redirect hack; new
  `/oauth/local/` in local mode).
- **API auth**: `server/apps/api/auth.py` (validator routing; reuse existing
  authlib dependency for local JWTs — no new runtime dependencies).
- **Management commands**: `api_test_token` (clear error when OIDC disabled), new
  local-users bootstrap command.
- **Frontend** (separate repo, no code change required): local mode = set
  `WODORE_OICD_ISSUER_URL=http://localhost:8000/oauth/local`,
  `WODORE_OICD_CLIENT_ID=wodore-local-dev`, any `WODORE_OICD_RESOURCE_ID`.
- **Ops**: `.env.test` drops `OIDC_OP_BASE_URL`; infisical dev env may set
  `OIDC_ENABLED=true` when the Zitadel stack is up.

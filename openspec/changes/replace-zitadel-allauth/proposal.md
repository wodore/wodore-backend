# Replace Zitadel with django-allauth + django-oauth-toolkit

## Why

Zitadel is the only separately-operated service in the Wodore stack, yet the
backend uses a fraction of what it offers: token issuance for the SPA, the
admin login page, and project roles. The Management API is unused (user admin
is manual in the Zitadel console), roles are already synced into Django groups
by `PermissionBackend`, and organizations live in Django anyway. Meanwhile
every API request pays an uncached introspection roundtrip to Zitadel
(10 s timeout) — a latency and availability liability. The built-in dev/test
provider (`server.apps.local_auth`) has already proven that Django can be the
OIDC issuer for this frontend. Consolidating auth into Django removes a
service, an upgrade path, and a secrets bundle while keeping the standard OIDC
surface the Quasar SPA speaks today — and that a future native Android app
(AppAuth + PKCE) can consume unchanged.

## What Changes

- Add **django-allauth** for account management: local login UI (replaces the
  Zitadel-hosted login), passwords, MFA (TOTP + recovery codes), email
  verification, password reset, session management, login rate limiting.
- Add **django-oauth-toolkit (DOT)** as the OIDC provider: authorization code
  + PKCE for public clients, `/token`, `/userinfo`, JWKS, discovery, JWT
  access tokens carrying a plain `roles` claim, refresh-token rotation.
- **BREAKING** — API token validation switches from Zitadel introspection to
  local JWT signature verification (multi-issuer routing during migration).
- **BREAKING** — frontend issuer URL changes from Zitadel to the Django
  backend. No user migration is needed (production has no user base yet);
  initial accounts are bootstrapped directly.
- Replace the `urn:zitadel:iam:org:project:{project}:roles` claim shape with
  a plain `roles` claim; Django groups become the single source of truth for
  authorization (no more Zitadel→Django sync).
- Remove `mozilla-django-oidc`, the Zitadel `PermissionBackend`, the
  introspection validator, and — after cutover — the `local_auth` dev/test
  provider app (superseded by DOT serving all environments).
- Register a second public PKCE client for the future native Android app
  (purely additive, no protocol changes).

## Capabilities

### New Capabilities

- `oidc-provider`: Django acts as the OIDC issuer via DOT — client
  registration, auth-code + PKCE flows, token/userinfo/JWKS/discovery
  endpoints, JWT access tokens with `roles` claims, refresh rotation, key
  management.
- `account-management`: allauth-based account lifecycle — login, logout,
  password management, email verification, MFA, sessions, throttling —
  serving both admin and end users.

### Modified Capabilities

- `api-token-validation`: validator routing gains a DOT JWT validator
  (local signature verification); Zitadel introspection validator is retired
  at cutover; roles are read from the `roles` claim instead of
  Zitadel-shaped claims.
- `optional-oidc`: `OIDC_ENABLED` keeps gating the provider surface, but the
  provider is now built-in (DOT) instead of the external Zitadel RP
  integration via `mozilla-django-oidc`; Zitadel-specific settings and the
  fail-fast discovery of an external provider are removed.
- `local-auth-provider`: superseded — its requirements are removed once DOT
  serves dev/test environments (same endpoints, standard implementation).

## Impact

- **Dependencies**: `+django-allauth`, `+django-oauth-toolkit`;
  `−mozilla-django-oidc`, `−authlib` (introspection client use).
- **Settings**: `server/settings/components/oidc.py` rewritten; new auth
  component for allauth/DOT; local-auth gates removed from `registry.py`.
- **Code**: `server/apps/api/auth.py` (validators), `server/core/oidc_permission.py`
  (permission backend → Django-groups based), `server/apps/local_auth/`
  (deleted), admin login flow, Unfold tab wiring.
- **Frontend** (`wodore-frontend-quasar`): issuer URL, roles claim shape,
  mobile-friendly login templates — coordinated release.
- **Data/ops**: OIDC signing keys stored in Infisical, token-table cleanup
  cron, Zitadel instance decommissioned after cutover; no user import —
  production has no user base yet.
- **Security posture**: password hashes move into the app DB (mitigations:
  Argon2, throttling, hardened DOT settings per RFC 9700 gates); local JWT
  verification removes the per-request introspection dependency.

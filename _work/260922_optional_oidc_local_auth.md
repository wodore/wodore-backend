# Optional OIDC + Local Dev Auth Provider

**Date**: 2026-09-22 · **Change**: [openspec `optional-oidc-local-auth`](../openspec/changes/optional-oidc-local-auth/)
**Branch**: `chore/optional-oidc` · **Base**: `main` @ `fc65ec8`

## Goal

Make Zitadel optional for dev/test while keeping it mandatory (and fail-fast) in
prod/staging; let the frontend authenticate directly against Django in local
mode with env-var changes only; make `AuthBearer`-protected API endpoints work
(and testable) in all modes.

## What was built

1. **`OIDC_ENABLED` / `LOCAL_AUTH_ENABLED` flags** (`components/oidc.py`,
   defaults from `DJANGO_ENV`; explicit env vars win; local provider hard-refused
   outside dev/test).
2. **Conditional Zitadel RP wiring**: no `/oidc/` URLs, no `admin/login/`
   redirect hack, no `PermissionBackend`, no `SessionRefresh`, **no import-time
   discovery fetch** when disabled; enabled-but-unreachable ⇒ startup aborts
   (`ImproperlyConfigured`).
3. **Local provider app** `server/apps/local_auth/`: discovery, authorize
   (PKCE S256, popup login form, `prompt=none` silent renew), token
   (authorization_code + dev/test password grant), userinfo with
   Zitadel-shaped `urn:zitadel:iam:org:project:roles` claim from Django
   groups, JWKS, end_session. Committed dev-only RSA key (safe: gated).
4. **Validator routing** (`server/apps/api/auth.py`): shared
   `BaseTokenValidator` (scope/role/group matching, byte-identical Zitadel
   semantics), `LocalJWTValidator` (verifies provider JWTs locally), clean 401
   "authentication not configured" when both flags off. Dead `require_auth`
   ResourceProtector removed (never imported anywhere).
5. **`local_auth_users` command** (idempotent fixture users), `api_test_token`
   guard, `.env.test` drops `OIDC_OP_BASE_URL`, `oicd→oidc` renames.

## Key discoveries during implementation

- **split-settings clobbering**: `include()` executes every file into ONE
  shared namespace; `environments/test.py` star-imports `development`, which
  re-imports `INSTALLED_APPS` from the `common` *module* - appends made in
  earlier components are wiped. Fix: conditional registrations moved to
  `components/registry.py`, loaded **last** in the include chain.
- **Preserved Zitadel quirk**: `AuthBearer(roles=[...])` without `groups=...`
  can never reject (groups=None short-circuits the combined check) - kept
  byte-identical per spec; documented in `tests/test_api_auth.py`.
- **axes** requires a request for `client.login()` in tests → `force_login`.
- Local tokens carry the roles claim **unqualified** (frontend reads it) and,
  when `ZITADEL_PROJECT` is set, **project-qualified** (introspection shape).

## Frontend (no code change needed)

```env
WODORE_OICD_ISSUER_URL=http://localhost:8000/oauth/local
WODORE_OICD_CLIENT_ID=wodore-local-dev
WODORE_OICD_RESOURCE_ID=local-dev
```

## Tests

- `tests/test_oidc_settings.py` - flag defaults per env (subprocess),
  fail-fast, guard, URL gating, admin classic login, `api_test_token` guard.
- `tests/test_local_auth.py` - full PKCE flow, silent renew, single-use codes,
  wrong verifier, redirect_uri mismatch, password grant, JWKS verification,
  end_session, idempotent users command.
- `tests/test_api_auth.py` - protected endpoints per mode, 401 semantics,
  validator routing, disabled-mode clean 401.

## Rollout

No prod change required (defaults preserve current behavior). Optional:
`OIDC_ENABLED=true` in infisical dev when the Zitadel stack is up.

Not smoked: Zitadel-mode live flow (local Zitadel down at implementation time -
disk-pressure; see ops notes).

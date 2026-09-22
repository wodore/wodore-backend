## 1. Renames & feature flag foundation

- [x] 1.1 `git mv server/settings/components/oicd.py oidc.py` and `server/core/oicd_permission.py oidc_permission.py`; update all imports/references (settings `__init__` load list, `environments/{development,production,local}.py`, `common.py` AUTHENTICATION_BACKENDS); verify no `oicd` references remain
- [x] 1.2 Add `OIDC_ENABLED = config("OIDC_ENABLED", cast=bool, default=not (DEBUG or _ENV == "test"))` in the renamed settings component (resolving the DEBUG/_ENV availability given component load order); gate the discovery fetch and the entire `if discovery_info:` block on it
- [x] 1.3 Make discovery failure raise `ImproperlyConfigured` when OIDC_ENABLED is true (replace the commented-out raise; keep a clear message naming the discovery URL); verify warning-only behavior is gone
- [x] 1.4 Conditionally wire the Zitadel RP surface: remove `/oidc/` include and the `admin/login/` redirect hack from `server/urls.py` when disabled; drop `PermissionBackend` from `AUTHENTICATION_BACKENDS` and skip `SessionRefresh` in `environments/*.py` when disabled
- [x] 1.5 Guard `api_test_token` against `OIDC_ENABLED=false` with a clear error; drop `OIDC_OP_BASE_URL` from `.env.test` and remove the now-dead `notset` workaround
- [x] 1.6 Add settings-level tests: flag defaults per environment (prod/staging/dev/test), explicit override wins, fail-fast on unreachable discovery, no import-time network when disabled

## 2. Local auth provider app

- [x] 2.1 Create `server/apps/local_auth/` app skeleton (no models; codes via cache) with routes mounted at `/oauth/local/` only when `LOCAL_AUTH_ENABLED` — including the `ImproperlyConfigured` guard for non-DEBUG/non-test activation and default `LOCAL_AUTH_ENABLED = (DEBUG or _ENV == "test") and not OIDC_ENABLED`
- [x] 2.2 Implement discovery endpoint (`/.well-known/openid-configuration`) with all endpoints, `code`/S256/`none` support flags, and issuer echo (per spec `local-auth-provider`)
- [x] 2.3 Implement dev login page + `authorize` endpoint: session check, `prompt=none` handling (immediate code vs `error=login_required`), PKCE `code_challenge` validation, single-use 60 s authorization codes in cache
- [x] 2.4 Implement `token` endpoint: `grant_type=authorization_code` with S256 verifier check, `grant_type=password`; RS256 JWT access + ID tokens via authlib using the local dev key (env `LOCAL_AUTH_PRIVATE_KEY_JWK` with committed dev-only default)
- [x] 2.5 Implement `userinfo` (token-protected) emitting `sub`, `email`, `name`, `picture` and the `urn:zitadel:iam:org:project:roles` claim built from Django groups; implement `jwks` and `end_session`
- [x] 2.6 Add `local_auth_users` management command (idempotent fixture users with passwords + groups, e.g. `admin@local.test`, `editor@local.test`); register help text per repo command conventions
- [x] 2.7 Provider integration tests: full code+PKCE flow modeled on the frontend's `oidc-client-ts` settings (discovery → authorize → token → userinfo), silent-renew `prompt=none` path, single-use codes, password grant, end-session, production-gate raise

## 3. API token validation routing

- [x] 3.1 Refactor `server/apps/api/auth.py`: extract scope/role/group matching and `validate_token` into a shared validator base; keep Zitadel introspection behavior byte-identical
- [x] 3.2 Add `LocalJWTValidator` (authlib `jwt.decode` against local JWKS key, exp check, `sub` → user, roles/groups claim reuse) and route `AuthBearer` to Zitadel/local/none by settings; clean 401 "authentication not configured" when neither flag is on
- [x] 3.3 End-to-end test per spec `api-token-validation`: local token via password grant hits a test-only protected Ninja endpoint (success, wrong-role 401, invalid-token 401, disabled-mode 401); confirm Zitadel-mode routing still instantiates the introspection validator
- [x] 3.4 Uncomment `auth=AuthBearer(roles=["perm:bookings"], ...)` on the huts booking endpoints only if the local roles/groups vocabulary supports it; otherwise leave commented and document why

## 4. Documentation & rollout

- [x] 4.1 Update `AGENTS.md` and `_work/` log: env flags (`OIDC_ENABLED`, `LOCAL_AUTH_ENABLED`), local mode workflow, frontend env vars (`WODORE_OICD_ISSUER_URL=http://localhost:8000/oauth/local`, `WODORE_OICD_CLIENT_ID=wodore-local-dev`, any `WODORE_OICD_RESOURCE_ID`)
- [x] 4.2 Run `inv tests` (all suites incl. new tests) and pre-commit; verify `uv lock --check` clean (no new dependencies expected)
- [x] 4.3 Manual smoke: local mode runserver → admin classic login works, frontend env-switched login + silent renew + logout works, protected endpoint 401/200 behavior; then `OIDC_ENABLED=true` against live Zitadel reproduces current behavior
- [x] 4.4 Open PR; note in description the rollout steps (no prod config change required — defaults preserve current behavior; optional `OIDC_ENABLED=true` in infisical dev when Zitadel stack is up)

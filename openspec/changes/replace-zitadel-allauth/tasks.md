# Replace Zitadel with django-allauth + django-oauth-toolkit

## 1. Foundation: dependencies and settings

- [ ] 1.1 Add `django-allauth` (account, mfa, sessions apps), `django-oauth-toolkit`, and `argon2-cffi` to `pyproject.toml` via uv; run `uv sync`
- [ ] 1.2 Create `server/settings/components/auth_local.py` (allauth: rate limits, `ACCOUNT_PREVENT_ENUMERATION`, email verification, Argon2 as first hasher; URL base paths) and wire it into the settings registry
- [ ] 1.3 Configure DOT in the OIDC component: JWT access tokens (RS256), `PKCE_REQUIRED`, `ROTATE_REFRESH_TOKEN` + `REFRESH_TOKEN_REUSE_PROTECTION`, RFC 9700 compliance gates, `ALLOWED_REDIRECT_URI_SCHEMES` (https + app scheme), authorization-code expiry ≤ 60 s
- [ ] 1.4 Source the DOT signing key from settings (Infisical-backed env var, JSON JWK); fail fast with `ImproperlyConfigured` when the provider is enabled and the key is missing; never commit the key
- [ ] 1.5 Flip `OIDC_ENABLED` semantics per spec: default true in all environments; remove `LOCAL_AUTH_ENABLED` usage from `registry.py` once the built-in provider covers dev/test (keep the app mounted until phase 5)

## 2. Account management (allauth)

- [ ] 2.1 Style the server-rendered allauth templates mobile-first (login, logout, password reset, email verification) — they are the primary SPA login surface at cutover (hosted redirect flow, per design D2a phase 1) and the future Android Custom Tab surface
- [ ] 2.2 Enable MFA (TOTP + recovery codes) and session view/revoke for users; decide and record staff-MFA policy (open question in design)
- [ ] 2.3 Redirect `/admin/` login to the unified account login preserving the continuation target
- [ ] 2.4 Port `local_auth_users` into the successor idempotent dev fixture users command (users + groups + passwords)
- [ ] 2.5 Add the SPA public PKCE client (and optionally the Android client row) via a data migration or fixture; seed groups `root/admin/editor/viewer` and `perm:*` roles as Django groups
- [ ] 2.6 Configure non-credentialed CORS for the SPA origin on the token and userinfo endpoints (required for the SPA's code exchange from a different domain)
- [ ] 2.7 After cutover — phase 2, gated on same-registrable-domain confirmation (design D2a): enable allauth headless browser mode for SPA-hosted login/MFA (credentialed CORS + `CSRF_TRUSTED_ORIGINS`) and move SPA login screens into the Quasar app

## 3. OIDC provider claims and permission bridge

- [ ] 3.1 Implement the DOT claims hook (OIDC ID-token/userinfo processing) building the plain `roles` claim from Django groups with `group:`-prefix conventions per spec
- [ ] 3.2 Replace `server/core/oidc_permission.py` Zitadel-sync backend with the Django-groups-as-source-of-truth mapping (or delete once no consumer remains)
- [ ] 3.3 Verify userinfo returns `sub`, `email`, `name`, `roles` for a valid token (integration test)

## 4. Token validation (dual-issuer window)

- [ ] 4.1 Add the built-in provider JWT validator to `server/apps/api/auth.py`: local RS256 verification, JWKS cached fetch, `iss`/`aud`/`exp` with clock-skew tolerance, roles from the `roles` claim
- [ ] 4.2 Make `_select_validator()` issuer-routed: built-in tokens verify locally whenever `OIDC_ENABLED`; Zitadel introspection stays available only while the migration flag is active; unknown `iss` → 401
- [ ] 4.3 Update `api_test_token` to mint built-in provider tokens; keep the disabled-mode error path
- [ ] 4.4 Update/extend the api-token-validation tests: local verify success, wrong-issuer 401, group/role matching against the `roles` claim, clean 401 when `OIDC_ENABLED=false`

## 5. Migration and cutover

- [ ] 5.1 Write the user import command (Zitadel export → Django users with unusable passwords + group mapping from the roles snapshot); dry-run mode with diff output
- [ ] 5.2 Invite/password-set email templates + audit logging on auth signals (login, logout, MFA changes, token failures); add `cleartokens` cron
- [ ] 5.3 Rehearse in staging: frontend (wodore-frontend-quasar) points issuer to the backend provider; verify login, refresh rotation, roles on protected endpoints
- [ ] 5.4 Production cutover: import users, send invites, flip frontend issuer; monitor for remaining Zitadel token usage during the dual-issuer window
- [ ] 5.5 After token metrics are clean: remove the migration flag and the Zitadel introspection validator

## 6. Cleanup and decommission

- [ ] 6.1 Delete `server.apps.local_auth` (app, urls, settings gate, tests) and the `LOCAL_AUTH_ENABLED` flag entirely
- [ ] 6.2 Remove `mozilla-django-oidc`, `SessionRefresh` middleware entry, `/oidc/` urls, and the `authlib` dependency; strip Zitadel settings (`ZITADEL_*`, discovery helper) from the OIDC component
- [ ] 6.3 Decommission the Zitadel instance and remove its Infisical secrets; document the rollback story (re-provision + re-invite) in the runbook/ops notes
- [ ] 6.4 Update `AGENTS.md` auth-mode section and `_work` notes; archive the change via openspec when verified

## 7. Verification gates (run throughout)

- [ ] 7.1 After each phase: `scripts/lane-run.sh .venv/bin/pytest` (lane DB — run `scripts/lane-db.sh create && scripts/sync-martin.sh` first if not yet provisioned)
- [ ] 7.2 Django system checks report no `oauth2_provider` error-level findings in production settings
- [ ] 7.3 OpenAPI schema unchanged for protected endpoints (`/v1/openapi.json`); frontend contract review signed off

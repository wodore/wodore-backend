# Replace Zitadel with django-allauth + django-oauth-toolkit

## 1. Modernize: allauth + DOT replace local_auth internals (dev/test, same issuer URL)

- [ ] 1.1 Add `django-allauth` (account, mfa, sessions apps), `django-oauth-toolkit`, and `argon2-cffi` to `pyproject.toml` via uv; run `uv sync`
- [ ] 1.2 Mount DOT at the existing `/oauth/local` issuer path so discovery URL and SPA client config stay unchanged; seed the SPA public PKCE client (and the Android client row) via data migration; thin compatibility views where DOT lacks an endpoint (`end_session`)
- [ ] 1.3 Configure DOT hardening: JWT access tokens (RS256), `PKCE_REQUIRED`, `ROTATE_REFRESH_TOKEN` + `REFRESH_TOKEN_REUSE_PROTECTION`, RFC 9700 compliance gates, `ALLOWED_REDIRECT_URI_SCHEMES` (https + app scheme), authorization-code expiry ≤ 60 s; signing key from Infisical with JWKS rotation support; fail-fast when missing outside dev/test
- [ ] 1.4 Create `server/settings/components/auth_local.py` (allauth rate limits, `ACCOUNT_PREVENT_ENUMERATION`, email verification, Argon2 as first hasher) and wire it into the settings registry
- [ ] 1.5 Enable MFA (TOTP + recovery codes), session view/revoke, and password-reset flows; decide and record staff-MFA policy; redirect `/admin/` login to the unified account login preserving the continuation target; style allauth templates (popup-sized, mobile-first) — they become the production login surface at the flip
- [ ] 1.6 Claims bridge: DOT emits both the legacy Zitadel-shaped roles claim (frontend continuity) and the plain `roles` claim from Django groups; retire `server/core/oidc_permission.py` Zitadel sync
- [ ] 1.7 Token renewal: DOT refresh tokens replace the session/`prompt=none` silent renew (small dev/test frontend change); popup session re-login stays as convenience
- [ ] 1.8 Port fixture users to the successor idempotent dev command; keep dev/test token convenience (password-grant client dev-only, or `api_test_token` mints DOT tokens)
- [ ] 1.9 Port provider tests to DOT (authorize + PKCE, token, userinfo, JWKS, roles, refresh rotation); delete the `local_auth` views/tokens/urls behind the same paths; system checks report no `oauth2_provider` error findings in production settings

## 2. Promote: flip the production default to the built-in provider (Zitadel stays rollback)

- [ ] 2.1 Flags end state: `OIDC_ENABLED` gates the built-in provider, defaulting true everywhere; retire `LOCAL_AUTH_ENABLED` and its dev/test gate together with the `local_auth` app; tests that want "no auth" set `OIDC_ENABLED=false` (clean-401 path)
- [ ] 2.2 Issuer-routed dual token validation in `server/apps/api/auth.py`: built-in JWTs verify locally (JWKS-cached, `iss`/`aud`, clock skew) while Zitadel introspection tokens stay accepted as long as Zitadel is enabled; unknown issuer → 401; tests for both issuers
- [ ] 2.3 Bootstrap initial production accounts directly (admin/editor via the fixture command) — no user migration needed (no production user base yet)
- [ ] 2.4 Audit logging on auth signals (login, logout, MFA changes, token failures); add `cleartokens` cron
- [ ] 2.5 Staging rehearsal, then flip the frontend default issuer (`WODORE_OICD_ISSUER_URL` → backend `/oauth` path) — frontend change is configuration only; verify popup + redirect login, refresh rotation, roles on protected endpoints; Zitadel stays selectable as rollback

## 3. Decommission: remove Zitadel

- [ ] 3.1 Monitor until token metrics show zero Zitadel usage, then remove the introspection validator and the Zitadel RP surface: `mozilla_django_oidc`, `SessionRefresh`, `/oidc/` routes, `ZITADEL_*` settings (incl. private-key loading and `oidc_permission.py` remnants)
- [ ] 3.2 Decommission the Zitadel instance and remove its Infisical secrets; document rollback (re-provision Zitadel, bootstrap accounts) in ops notes
- [ ] 3.3 Update `AGENTS.md` auth-mode section and `_work` notes; archive the change via openspec when verified

## 4. Verification gates (run throughout)

- [ ] 4.1 After each phase: `scripts/lane-run.sh .venv/bin/pytest` (lane DB — run `scripts/lane-db.sh create && scripts/sync-martin.sh` first if not yet provisioned)
- [ ] 4.2 OpenAPI schema unchanged for protected endpoints (`/v1/openapi.json`); frontend contract review signed off per phase

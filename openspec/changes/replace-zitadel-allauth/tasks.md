# Replace Zitadel with django-allauth + django-oauth-toolkit

## 1. Promote: local provider becomes production default (Zitadel stays rollback)

- [ ] 1.1 Remove the `LOCAL_AUTH_ENABLED` dev/test-only gate: default true in all environments, allowed in production; both auth flags may be active simultaneously
- [ ] 1.2 Production key guard: require `LOCAL_AUTH_PRIVATE_KEY_JWK` (Infisical-backed) when running outside dev/test — fail fast if unset or if the committed dev key would be used; dev/test keep the committed dev key
- [ ] 1.3 Restrict the password grant to dev/test; production serves authorization-code + PKCE only
- [ ] 1.4 Issuer-routed dual token validation in `server/apps/api/auth.py`: local JWTs verify locally (JWKS-cached, `iss`/`aud`, clock skew) and Zitadel introspection tokens remain accepted while Zitadel is enabled; unknown issuer → 401; tests for both issuers
- [ ] 1.5 Login throttling/lockout on the local provider's login form (failed-attempt limits)
- [ ] 1.6 User import command (Zitadel export → Django users with unusable passwords + group mapping from the roles snapshot); dry-run mode with diff output; document interim password reset as admin-driven (open question: minimal reset flow?)
- [ ] 1.7 Invite/password-set email templates + audit logging on auth signals (login, logout, token failures)
- [ ] 1.8 Style the `local_auth` login template (popup-sized, mobile-first) — it becomes the production login surface at the default flip
- [ ] 1.9 Staging rehearsal, then flip the frontend default issuer (`WODORE_OICD_ISSUER_URL` → backend `/oauth/local`) — frontend change is configuration only; verify popup + redirect login, session-based renew, roles on protected endpoints; Zitadel stays selectable as rollback

## 2. Modernize: allauth + DOT replace local_auth internals (same issuer URL)

- [ ] 2.1 Add `django-allauth` (account, mfa, sessions apps), `django-oauth-toolkit`, and `argon2-cffi` to `pyproject.toml` via uv; run `uv sync`
- [ ] 2.2 Mount DOT at the existing issuer path so the discovery URL and SPA client config stay unchanged; seed the SPA public PKCE client (and the Android client row) via data migration; thin compatibility views where DOT lacks an endpoint (`end_session`)
- [ ] 2.3 Configure DOT hardening: JWT access tokens (RS256), `PKCE_REQUIRED`, `ROTATE_REFRESH_TOKEN` + `REFRESH_TOKEN_REUSE_PROTECTION`, RFC 9700 compliance gates, `ALLOWED_REDIRECT_URI_SCHEMES` (https + app scheme), authorization-code expiry ≤ 60 s; signing key in Infisical with JWKS rotation support; fail-fast when missing
- [ ] 2.4 Create `server/settings/components/auth_local.py` (allauth rate limits, `ACCOUNT_PREVENT_ENUMERATION`, email verification, Argon2 as first hasher) and wire it into the settings registry
- [ ] 2.5 Enable MFA (TOTP + recovery codes), session view/revoke, password-reset flows; decide and record staff-MFA policy; redirect `/admin/` login to the unified account login preserving the continuation target
- [ ] 2.6 Claims bridge: DOT emits both the legacy Zitadel-shaped roles claim (frontend continuity) and the plain `roles` claim from Django groups; retire `server/core/oidc_permission.py` Zitadel sync
- [ ] 2.7 Switch token renewal from session/`prompt=none` silent renew to DOT refresh tokens (small frontend change); keep popup session re-login as convenience
- [ ] 2.8 Port fixture users to the successor idempotent dev command; port provider tests (auth-code + PKCE, token, userinfo, JWKS, roles) to DOT; delete the `local_auth` views/tokens/urls behind the same paths
- [ ] 2.9 Update `api_test_token` to mint DOT tokens; confirm system checks report no `oauth2_provider` error findings in production settings

## 3. Decommission: remove Zitadel

- [ ] 3.1 Monitor until token metrics show zero Zitadel usage, then remove the introspection validator and the Zitadel RP surface: `mozilla_django_oidc`, `SessionRefresh`, `/oidc/` routes, `ZITADEL_*` settings (incl. private-key loading and `oidc_permission.py` remnants)
- [ ] 3.2 Flags end state: built-in provider always on (`OIDC_ENABLED` gates it, default true; remove `LOCAL_AUTH_ENABLED`); tests that want "no auth" set it false
- [ ] 3.3 Decommission the Zitadel instance and remove its Infisical secrets; document rollback (re-provision + re-invite) in ops notes
- [ ] 3.4 Update `AGENTS.md` auth-mode section and `_work` notes; archive the change via openspec when verified

## 4. Verification gates (run throughout)

- [ ] 4.1 After each phase: `scripts/lane-run.sh .venv/bin/pytest` (lane DB — run `scripts/lane-db.sh create && scripts/sync-martin.sh` first if not yet provisioned)
- [ ] 4.2 OpenAPI schema unchanged for protected endpoints (`/v1/openapi.json`); frontend contract review signed off per phase

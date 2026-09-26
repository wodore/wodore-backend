# Zitadel → allauth + DOT proposal (260926)

Planning session that produced the OpenSpec change
`openspec/changes/replace-zitadel-allauth/` (branch/worktree
`replace-zitadel-allauth`).

## Context / decision trail

- Zitadel is underutilized: only token issuance + login page + project roles;
  Management API unused, roles already synced into Django groups, orgs live in
  Django. Per-request introspection (uncached, 10 s timeout) is a latency/
  availability liability.
- Options evaluated:
  - **A: allauth headless** — drops OIDC; every auth flow needs a native
    re-implementation for a future Android app; session-token semantics don't
    map to mobile.
  - **B: allauth + django-oauth-toolkit** — Django becomes the OIDC IdP;
    frontend keeps standard OIDC (issuer URL change only); Android = AppAuth
    + PKCE client, purely additive. **Chosen.**
  - C: keep Zitadel, swap mozilla-django-oidc for allauth-as-RP — no stack
    reduction.
- Security posture accepted consciously: credentials + signing keys move into
  the app DB (Argon2, Infisical-held keys, throttling, RFC 9700 DOT gates);
  login availability couples to the app (existing JWTs survive downtime via
  local verify); supply-chain duty = pin + advisories for both libs
  (allauth 65.13.0, DOT oauthlib bumps are recent evidence of responsive
  maintenance).

## Key design points (see design.md)

- Plain `roles` claim from Django groups (group: prefix convention preserved);
  Zitadel claim shape only as migration fallback.
- Dual-issuer window via issuer-routed `_select_validator()`; rollback =
  frontend repoints to Zitadel until decommission.
- `OIDC_ENABLED` now defaults true everywhere (built-in provider replaces
  `local_auth`); `LOCAL_AUTH_ENABLED` dies.
- User cutover is invite-based (Zitadel doesn't export passwords); watch for
  phishing look-alikes during the window.

## Migration restructure — final order (260926, latest steer)

No production users exist yet → no user migration at all. Order is now:
1) **modernize** allauth+DOT in dev/test under the SAME issuer URL
   (local_auth deleted behind its URLs; production untouched),
2) **flip** the production default once (flags per D5; dual issuer-routed
   validation for Zitadel rollback; bootstrap accounts directly),
3) **decommission** Zitadel.
The earlier "promote local_auth first" idea was dropped — productionizing
the hand-rolled provider would have been throwaway work without a user
base to migrate.

## Migration restructure (260926, later)

User steer: phase 1 keeps Zitadel as rollback and promotes the existing
`local_auth` flow to production *default* (both flows already exist — the
change is defaults + production guards: gate removal, forced signing key,
user import/invites, issuer-routed dual validation, throttling, password
grant dev-only). allauth+DOT becomes phase 2 "modernize" under the SAME
issuer URL (frontend config untouched; DOT emits legacy claim shape too);
phase 3 decommissions Zitadel. See design.md Migration Plan + tasks.md.

## Implementation notes (260926, phase 1 "modernize" applied)

- DOT 3.4.1 issues **opaque DB-backed access tokens** (JWTs are ID-token
  only). Spec updated: validation = local DB lookup (instant revocation,
  live roles from Django groups); api_test_token mints JWTs that verify
  via signature + exact issuer match (no path-suffix matching - a forged
  `evil.example/oauth/local` issuer must fail).
- Issuer matching is exact against request-derived + configured issuers
  (`LOCAL_AUTH_ALLOWED_ISSUERS`).
- Password grant: dev/test-only confidential client seeded by
  `local_auth_users` (needs client_id+secret now). DOT RFC 9700 gates stay
  off because of it - revisit at DOT 4.0 (gate default flips) by switching
  test convenience to `api_test_token`.
- debug_toolbar middleware survived the star-import into the test env and
  injected into HTML responses (local-only quirk); test.py strips it now.
- Full suite: 144 passed; `manage.py check` in production settings (with
  key env vars): 0 issues.

## Open follow-ups

- Login UX is phased (D2a): hosted allauth login at cutover (different
  domains → first-party-cookie redirect flow), SPA-hosted login via headless
  browser mode as optional phase 2 — feasible only if SPA and backend share
  the registrable domain (same-site); otherwise blocked by Safari/Chrome
  third-party-cookie rules.
- Staff-MFA enforcement timing.
- Frontend coordination (wodore-frontend-quasar): issuer, roles claim, login
  template styling.
- Worktree note: lane DB + martin not provisioned yet (docs-only work); run
  `scripts/lane-db.sh create && scripts/sync-martin.sh` before implementing.

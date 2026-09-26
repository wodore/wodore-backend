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

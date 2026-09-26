# Replace Zitadel with django-allauth + django-oauth-toolkit

## Context

Today the backend runs two auth modes behind feature flags
(`server/settings/components/oidc.py`):

- **Zitadel (prod/staging)**: `mozilla-django-oidc` provides the RP surface
  (admin login, SessionRefresh, PermissionBackend); the Quasar SPA runs
  auth-code + PKCE against Zitadel; Django Ninja's `AuthBearer`
  (`server/apps/api/auth.py`) validates access tokens via Zitadel's
  introspection endpoint using a private-key JWT client assertion — an
  uncached blocking HTTP call (10 s timeout) on every protected request.
- **Local provider (dev/test)**: `server.apps.local_auth` is a hand-rolled
  OIDC issuer (authorize + PKCE, token incl. password grant, userinfo, JWKS,
  end-session) that mimics Zitadel's claim shapes; `LocalJWTValidator`
  verifies its RS256 JWTs locally.

Zitadel's Management API is unused; roles from Zitadel claims are synced into
Django groups; organizations live in Django regardless. Frontend and future
native clients speak standard OIDC.

## Goals / Non-Goals

**Goals:**

- One auth stack inside Django: allauth (accounts) + DOT (OAuth2/OIDC
  provider) — no external IdP service to operate.
- Frontend keeps standard OIDC (auth-code + PKCE); issuer URL is the only
  protocol-level change.
- API token validation becomes local JWT signature verification (no network
  call per request), with issuer-based routing during migration.
- Django groups become the single authorization source of truth.
- A second public PKCE client for a future Android app (AppAuth, RFC 8252)
  is additive only.
- Preserved: `AuthBearer(roles=…, groups=…)` endpoint semantics.

**Non-Goals:**

- Enterprise SSO federation (SAML), org delegation, or a separate audit-log
  UI — accepted losses vs. Zitadel.
- Changing endpoint authorization rules or the roles/groups vocabulary
  (`root/admin/editor/viewer`, `perm:*`).
- Migrating passwords (impossible — Zitadel does not export them).
- The Android app itself (client registration only).
- Social login providers (allauth capability stays available, none
  configured initially).

## Decisions

### D1: allauth + DOT (Option B) over allauth-headless (A) or Zitadel (C)

Headless would throw away the SPA's existing OAuth client code, force a
native re-implementation of every auth flow on Android, and couple app
sessions to Django session semantics (no refresh tokens). Keeping Zitadel
retains an entire external service for features we don't use. B keeps the
frontend flow identical, matches mobile best practice (browser + PKCE +
refresh), and reuses the proven `local_auth` pattern with maintained
components. Alternative hybrid (allauth + SimpleJWT) rejected: custom
non-standard token endpoint = a worse B.

### D2: Division of labor

- **allauth**: user model-facing flows — login/logout UI (replaces the
  Zitadel-hosted page), passwords, email verification, MFA (TOTP + recovery
  codes), sessions (view/revoke), login throttling. Apps enabled:
  `account`, `mfa`, `sessions`. No `socialaccount` providers initially.
- **DOT**: OAuth2/OIDC machinery — public PKCE clients (SPA, later
  Android), `/authorize` (uses Django login = allauth), `/token`,
  `/userinfo`, `/jwks`, discovery; JWT access tokens (RS256) with a
  `roles` claim.
- **Django Ninja + `AuthBearer`**: resource server — local JWT
  verification.

### D2a: Login UX — hosted login at cutover, SPA-hosted login later

The SPA and the backend live on **different domains**, which rules out the
simplest same-origin form of SPA-hosted login. Login UX is therefore
phased:

- **Phase 1 (cutover)**: hosted allauth login on the backend domain via the
  standard authorization-code flow. Two equivalent UX modes: a full-page
  redirect, or a **popup** (`window.open` → `/authorize`, as with Zitadel
  today): the popup is a top-level browsing context on the backend domain,
  so all cookies remain first-party and the different-domains problem
  disappears; the popup lands on a registered SPA callback route which
  `postMessage`s the code to the opener and closes. Popups must open from
  a user gesture (blocker rules); mobile browsers use the redirect
  fallback. No `SameSite=None`, no credentialed CORS — only plain
  (non-credentialed) CORS on `/o/token/` and `/o/userinfo/` for the SPA
  origin. A surviving backend session cookie (set inside the popup) makes
  later logins a brief popup flash — no iframe silent renew (DOT lacks
  `prompt=none`; irrelevant), routine renewal stays on rotated refresh
  tokens. Hosted templates are styled mobile-first — they render inside
  the popup at cutover and remain the surface for the future Android
  client.
- **Phase 2 (post-cutover, optional)**: the SPA renders its own
  login/MFA/password-reset screens via allauth headless **browser mode**.
  Feasible **iff** SPA and backend share the same registrable domain (e.g.
  `app.wodore.com` + `hub.wodore.com`): the cross-origin fetch is then
  still *same-site*, so the session cookie works with credentialed CORS +
  `CSRF_TRUSTED_ORIGINS` and no `SameSite=None`. If the SPA sits on an
  unrelated registrable domain, the session cookie would be third-party
  (blocked by Safari ITP and Chrome's third-party-cookie restrictions) —
  in that case the popup/redirect flow from phase 1 is the permanent
  solution (or consolidate hosts before building phase 2).
- Token renewal uses rotated refresh tokens in both phases — no iframes or
  popups at any point.
- With the phased migration (modernize → flip → decommission, below), the
  allauth templates serve from day one of the production flip; the
  existing `local_auth` login form only bridges dev/test until DOT
  replaces it under the same URLs, and renewal switches to refresh tokens
  in that same step.

### D3: Claims — plain `roles` claim, groups stay authoritative in Django

Replace the `urn:zitadel:iam:org:project:{project}:roles` shape with a plain
`roles` claim built from Django group memberships. Preserve the value
semantics `AuthBearer` already expects: entries are role names, `group:`-
prefixed entries are groups (so `root`, `admin`, `editor`, `viewer` group
memberships appear both as groups and — via the existing prefix convention —
authorize `groups=[…]` checks; `perm:*` entries stay roles). The
Zitadel→Django sync direction disappears; `oidc_permission.py` is replaced
by a thin claims hook reading Django groups. During migration the validator
accepts both claim shapes.

### D4: Token validation — local JWT verify, issuer-routed, dual-issuer from phase 1

Validation becomes issuer-routed instead of mode-XOR: local provider JWTs
verify locally (JWKS cached, `iss` + `aud` checked, clock-skew tolerance) —
the existing `LocalJWTValidator` pattern, generalized; Zitadel
introspection remains accepted in parallel whenever Zitadel is still
enabled, so rollback is a frontend config repoint. This lands in the
promote phase. After Zitadel decommission the introspection validator,
`mozilla_django_oidc`, and Zitadel settings are deleted — no token
validation does network calls anymore.

### D5: Flags — modernize first, flip once

Production has no user base yet, so there is nothing to migrate and no
reason to productionize the hand-rolled provider: the built-in stack
(allauth + DOT) is built and exercised in dev/test first — replacing
`local_auth` under the same issuer URL — and only then does the
production default flip, once, to the final stack. During modernize,
`LOCAL_AUTH_ENABLED` keeps gating the built-in provider in dev/test
(semantics unchanged for frontends). At the flip it is retired together
with the `local_auth` app and its dev/test gate: `OIDC_ENABLED` gates the
built-in provider, defaults true everywhere, and Zitadel remains
selectable via explicit configuration as rollback until decommission
(issuer-routed validation, D4, accepts both). Tests that want "no auth"
set `OIDC_ENABLED=false` and get the clean-401 path that already exists.

### D6: Security hardening baseline

- Password hasher: **Argon2**.
- allauth: `ACCOUNT_RATE_LIMITS` (login + reset), `ACCOUNT_PREVENT_ENUMERATION`, verified-email requirements.
- DOT: `PKCE_REQUIRED=True`, `ROTATE_REFRESH_TOKEN=True` +
  `REFRESH_TOKEN_REUSE_PROTECTION=True`, exact-match redirect URIs,
  `ALLOWED_REDIRECT_URI_SCHEMES` = `https` + private-use app scheme for
  Android, RFC 9700 compliance gates on (`COMPLIANT_BCP_RFC9700_*`),
  `AUTHORIZATION_CODE_EXPIRE_SECONDS` ≤ 60.
- Signing keys: RS256 keypair in Infisical (never in git); JWKS rotation
  supported by key id; fail-fast at startup if the key is missing while
  the provider is enabled.
- Ops: `cleartokens` cron for token/grant tables; audit logging on auth
  signals (login, logout, MFA changes, token issuance failures).

### D7: Users — no migration needed

Production has no user base yet, so there is no import/invite cutover:
initial accounts (admin/editor) are bootstrapped directly with the dev
fixture-style command before the flip. The invite/password-set email
machinery drops off the critical path; allauth's email verification
remains for future self-registration.

## Risks / Trade-offs

- [Credentials + signing keys concentrate in the app DB] → Argon2,
  Infisical-held keys, encrypted backups, tight DB access, key-rotation
  runbook.
- [Login unavailable while the app is down] → accepted; existing JWTs keep
  working (local verify), deploys are short; admin has local Django login.
- [Credential-stuffing load shares processes with the API] → allauth rate
  limits + account lockout + reverse-proxy rate limiting on `/account/` and
  `/o/`.
- [Two libraries' CVE exposure instead of one product] → pin versions,
  Dependabot/Renovate on advisories, fast patch policy (both projects have
  a responsive record; allauth 65.13.0 and DOT's oauthlib bumps show it).
- [No org-level "force MFA" policy like Zitadel] → MFA available per user;
  staff-MFA enforcement decided at review time (see Open Questions).
- [Invite-cutover phishing look-alikes] → clear signposting, short window,
  consistent sender branding.
- [Losing silent-Zitadel-SSO between admin and SPA] → both now share the
  same Django session/SSO domain — net improvement.

## Migration Plan

Three phases. Production has no user base yet, so there is no user
migration to schedule — the final stack is built first and the production
default flips once.

1. **Modernize (dev/test first)** — allauth (accounts, MFA, password
   reset, sessions) and DOT (refresh tokens, rotation, RFC 9700
   hardening, key management) replace the `local_auth` internals **under
   the same issuer URL**, so dev/test frontends keep their discovery URL
   and client config: DOT emits both the legacy Zitadel-shaped roles
   claim (frontend continuity) and the plain `roles` claim;
   refresh-token renewal replaces the session/`prompt=none` silent
   renew; thin compatibility views cover endpoint differences (e.g.
   `end_session`). The `local_auth` app is deleted behind its URLs.
   Production is untouched in this phase.
2. **Promote (default flip)** — the production default flips to the
   built-in provider: flags per D5 (`OIDC_ENABLED` gates the built-in
   provider, default true; `LOCAL_AUTH_ENABLED` retired with its gate);
   issuer-routed dual token validation (D4) accepts built-in JWTs and
   Zitadel tokens side by side; initial accounts are bootstrapped
   directly (D7); staging rehearsal; then the frontend default issuer
   flips — configuration only. Zitadel stays fully functional as
   rollback.
3. **Decommission** — once token metrics show zero Zitadel usage: remove
   the introspection validator and the Zitadel RP surface
   (`mozilla_django_oidc`, `SessionRefresh`, `/oidc/` routes,
   `ZITADEL_*` settings), decommission the instance and its Infisical
   secrets.

**Rollback**: modernize touches no production system; during promote,
rollback is a frontend config repoint (Zitadel stays live). After
decommission, rollback = re-provision Zitadel (accepted).

## Open Questions

- SPA host vs. backend host: do they share the registrable domain
  (`*.wodore.com`)? Decides whether phase 2 (SPA-hosted login per D2a) is
  feasible as specced or requires consolidating hosts; the issuer stays on
  the backend origin either way.
- Enforce MFA for staff/admin accounts (allauth config) at the flip or later?
- Should `api_test_token` mint DOT tokens directly (management command)
  once password grant is dev-only?
- Android client registration timing (row only — can be added anytime).
- Email sender/branding for account + verification mails (uses existing
  Django email config; needs a template pass).

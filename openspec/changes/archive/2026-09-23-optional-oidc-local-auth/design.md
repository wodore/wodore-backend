## Context

Zitadel is the single identity provider today: the Django admin logs in via
`mozilla_django_oidc` (session flow), the Quasar frontend logs in directly against
Zitadel (`oidc-client-ts`, authorization code + PKCE, popup sign-in, silent renew),
and protected API endpoints are meant to verify Zitadel access tokens via authlib
introspection (`AuthBearer`, currently only commented-out usages).

Couplings today:

- `settings/components/oicd.py` fetches the discovery document **at settings
  import**; on failure it warns and silently skips setting `OIDC_OP_*` endpoints —
  every `manage.py` command does network I/O, and the failure surfaces only as a
  500 on `/oidc/authenticate/`.
- `server/urls.py` unconditionally mounts `/oidc/` and the `admin/login/` redirect
  hack; `common.py` unconditionally registers `PermissionBackend`.
- Frontend requirements (verified in `wodore-frontend-quasar/src/services/auth.ts`
  and `stores/auth-store.ts`): discovery from `{authority}`, `response_type=code`
  with PKCE, `signinPopup()`, `automaticSilentRenew` (`prompt=none`),
  `loadUserInfo`, `signoutSilent()` (`end_session_endpoint`), scopes
  `openid profile email offline_access urn:zitadel:iam:org:project:id:<rid>:aud
  urn:zitadel:iam:org:projects:roles`, and roles read from the
  `urn:zitadel:iam:org:project:roles` claim (a map keyed by role names).
- `authlib` is already a runtime dependency (JWT encode used by the introspection
  validator).

## Goals / Non-Goals

**Goals:**

- Zitadel optional for dev/test; mandatory & fail-fast in prod/staging.
- Frontend works against plain Django in local mode with **env-var changes only**
  (no frontend code changes).
- Protected API endpoints (`AuthBearer`) work in all three modes: Zitadel
  introspection, local JWT, or clean 401 when nothing is configured.
- Local mode is hard-gated to DEBUG/test environments — unsafe-by-design but
  impossible to enable in production.
- Remove import-time network I/O from the disabled path; kill the silent-failure
  trap.

**Non-Goals:**

- Replacing Zitadel in production; multi-provider support beyond Zitadel+local.
- Local password/user management UI (bootstrap command is enough).
- Wiring the Django admin to the local provider (admin keeps classic Django login
  in local mode; the local provider speaks OIDC, so this remains a possible
  follow-up).
- Touching the frontend repository (env vars only).
- Revoking/rotating local dev keys (dev-only key material, may be committed).

## Decisions

### D1: One flag with mode semantics, two switches total

`OIDC_ENABLED = config("OIDC_ENABLED", cast=bool, default=not (DEBUG or _ENV == "test"))`
controls the Zitadel RP surface (discovery, `/oidc/` URLs, admin redirect hack,
`PermissionBackend`, `SessionRefresh`).

`LOCAL_AUTH_ENABLED = config("LOCAL_AUTH_ENABLED", cast=bool, default=(DEBUG or _ENV == "test") and not OIDC_ENABLED)`
controls the built-in provider. Settings additionally **raise**
`ImproperlyConfigured` if `LOCAL_AUTH_ENABLED` is true outside DEBUG/test — an
explicit override cannot smuggle it into production.

*Alternative considered*: a single tri-state `AUTH_MODE=zitadel|local|off`. Rejected:
the two concerns (Zitadel RP vs local provider) are independent in principle
(e.g. dev *with* Zitadel stack could later also run local users), and two booleans
with guarded defaults read clearer in env files.

Resulting modes:

| Mode | OIDC_ENABLED | LOCAL_AUTH_ENABLED | Admin login | Frontend | API bearer |
|---|---|---|---|---|---|
| prod/staging | true | impossible | Zitadel SSO | Zitadel | introspection |
| dev + Zitadel | true (explicit) | off | Zitadel SSO | Zitadel | introspection |
| dev local (default) | false | true | Django form | local provider | local JWT |
| test | false | true | n/a | programmatic | local JWT |

### D2: Hand-rolled minimal OIDC provider over django-oauth-toolkit

A small Django app (`server/apps/local_auth/`) implements exactly the endpoints
`oidc-client-ts` needs under `/oauth/local/`:

- `GET /.well-known/openid-configuration` — discovery with
  `authorization_endpoint`, `token_endpoint`, `userinfo_endpoint`, `jwks_uri`,
  `end_session_endpoint`, `response_types_supported: ["code"]`,
  `code_challenge_methods_supported: ["S256"]`, `prompt_values_supported:
  ["none"]`.
- `GET /authorize` — requires an authenticated Django session; supports
  `prompt=none` (silent renew: authenticated → immediate 302 with code,
  unauthenticated → 302 with `error=login_required`), otherwise renders a
  minimal dev login/consent page (username+password POST → session → redirect
  with code). PKCE `code_challenge` required for public clients; authorization
  codes are single-use, short-lived (60 s), stored in cache.
- `POST /token` — `grant_type=authorization_code` (PKCE S256 verification) and,
  test/dev convenience, `grant_type=password` (direct token for integration
  tests and curl). Issues JWT access token + ID token (authlib, RS256).
- `GET /userinfo` — requires the access token; emits `sub`, `email`, `name`,
  `picture` (gravatar fallback) **and the Zitadel-shaped claims**
  `urn:zitadel:iam:org:project:roles` (map: `{role: {...}}` from Django groups)
  plus `urn:zitadel:iam:org:projects:roles` for compatibility.
- `GET /jwks` — public JWKS for the local dev key.
- `GET /end_session` — clears session, 302 to `post_logout_redirect_uri`.

*Rationale vs django-oauth-toolkit*: DOT is a production-grade provider whose
strengths (strict spec compliance, scope registry, client management, migrations)
become friction here — it validates requested scopes against a database registry
(the frontend sends Zitadel URN scopes that would have to be seeded), custom
Zitadel-shaped claims require subclassing its views, and it would ship as a
permanent dependency used only in dev/test. The hand-rolled surface is ~300–400
lines with zero new dependencies (authlib already present), full control over
claim shapes (→ zero frontend changes), and is entirely deletable. Unsafe edges
(no rate limiting, permissive origins) are acceptable because D1 hard-gates the
whole app to DEBUG/test.

*Alternative considered*: a dev-token endpoint + frontend "dev login" mode.
Rejected: needs frontend code changes, violating the env-vars-only goal.

### D3: Claim shim keeps the frontend at env-vars-only

The local provider emits `urn:zitadel:iam:org:project:roles` (exactly the claim
the frontend store reads) built from Django group names. Local mode then needs
only:

```
WODORE_OICD_ISSUER_URL=http://localhost:8000/oauth/local
WODORE_OICD_CLIENT_ID=wodore-local-dev
WODORE_OICD_RESOURCE_ID=local-dev   # only used inside the scope string; ignored by provider
```

*Trade-off*: the claim name is Zitadel-specific forever. Accepted — the frontend
already depends on it, and renaming the claim repo-wide is a separate frontend
change if ever desired.

### D4: Validator routing on AuthBearer, shared matching

`AuthBearer` selects a validator at instantiation from settings: Zitadel
introspection (unchanged) when `OIDC_ENABLED`; a `LocalJWTValidator` (authlib
`jwt.decode` against the local JWKS, `sub` → user, roles claim from the token)
when `LOCAL_AUTH_ENABLED`; otherwise returns a clean 401
("authentication not configured") instead of crashing on missing
`OIDC_OP_INTROSPECTION_ENDPOINT`. Scope/role/group matching
(`match_token_scopes/roles/groups`, `validate_token`) moves to a shared base so
both validators reuse it; role/group semantics stay identical
(non-`group:`-prefixed = roles, `group:`-prefixed = groups).

### D5: Fail-fast Zitadel discovery, no import-time network when disabled

When `OIDC_ENABLED` is true, discovery failure raises `ImproperlyConfigured` at
startup (flipping today's commented-out raise). When false, no fetch happens at
all — commands become network-free and `.env.test` drops `OIDC_OP_BASE_URL`.

### D6: Local key material and users

RS256 keypair from env (`LOCAL_AUTH_PRIVATE_KEY_JWK`, dev default: a committed
512-byte dev-only RSA key) — committed is acceptable because the provider cannot
run in production (D1). Users via a small management command
(`local_auth_users`) creating fixture users (e.g. `admin@local.test`,
`editor@local.test`) with passwords and groups; tests reuse it or mint tokens
via the password grant.

### D7: Renames ride along

`git mv components/oicd.py oidc.py`, `core/oicd_permission.py →
oidc_permission.py`, update the ~6 reference sites. No behavior change; done
first so new work lands under correct names.

## Risks / Trade-offs

- [Hand-rolled provider has OIDC-flow bugs (popup/silent renew edge cases)] →
  integration tests drive the full code+PKCE flow with an HTTP client modeled on
  `oidc-client-ts` settings; provider is dev/test-only.
- [Password grant is insecure] → acceptable by D1 gating; documented in the
  endpoint docstring; never registered in prod settings.
- [Committed dev private key] → provider hard-gated to DEBUG/test; key signs
  nothing in prod. Rotate by regenerating the fixture, not secret-management.
- [Claim shim locks in Zitadel naming] → documented in D3; frontend rename is an
  optional future change.
- [Someone sets LOCAL_AUTH_ENABLED in prod infisical] → settings raise
  `ImproperlyConfigured` unless DEBUG/test; deployment fails loudly at boot.
- [Protected-endpoint routing regressions for Zitadel mode] → routing covered by
  unit tests per mode; Zitadel validator class itself stays untouched.

## Migration Plan

1. Merge behind no flag (behavior identical in prod: OIDC_ENABLED defaults true
   there). Rollback = revert; no schema changes beyond the new app's none (no
   models — codes in cache, users via command).
2. Infisical: optionally set `OIDC_ENABLED=true` in dev when the Zitadel stack
   is up; otherwise dev defaults to local mode.
3. Frontend: document the three env vars for local mode (no code change).

## Open Questions

- Token lifetimes in local mode (proposal: access 1 h, ID 5 min — matches
  silent-renew expectations) — confirm during implementation.
- Should `api_test_token` grow a `--local` mode that fetches a token from the
  local provider? Nice-to-have, not blocking.

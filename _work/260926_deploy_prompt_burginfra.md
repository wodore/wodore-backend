# Deploy prompt — wodore-backend `a6c406e` (PR #183: auth stack + user model swap)

> Hand this to the burginfra agent as-is.

## Context

PR #183 (auth modernization) is merged to `main`. **Production behavior is unchanged** — Zitadel stays the default provider (`AUTH_PROVIDER` unset → `zitadel` outside dev/test; SSO admin login, introspection validation all work exactly as before). But the release contains two operational items:

1. New dependencies (in `uv.lock`): `django-allauth`, `django-oauth-toolkit`, `argon2-cffi`, `fido2`
2. **Custom user model swap** (`auth.User` → `accounts.User`, email = login id, pks preserved) — needs a ONE-TIME migration bootstrap on every existing database

## Steps — per environment (staging first, then production)

1. Deploy the code as usual (build/image incl. lockfile deps).
2. Run **once** in the app container/migration job:
   ```bash
   python manage.py bootstrap_user_model
   ```
   - Creates `accounts_user`, copies all users with primary keys/passwords/groups/flags, re-points the user FK constraints, then applies all remaining migrations itself.
   - Idempotent (safe to re-run) and correct on fresh databases (plain migrate).
   - **`manage.py migrate` alone FAILS on existing databases** (`InconsistentMigrationHistory`) — `bootstrap_user_model` is the required entry point this one time. Plain `migrate` works again afterwards.
3. `python manage.py collectstatic` (new account-page CSS).
4. **No env/Infisical changes needed.** Do NOT set `AUTH_PROVIDER` in production. (Later, staging-only rehearsal of the new stack: `AUTH_PROVIDER=builtin` + `LOCAL_AUTH_PRIVATE_KEY_JWK` (private RSA JWK, JSON) — coordinate first, that's the phase-2 flip.)
5. Also run `bootstrap_user_model` once against the `wodore_template` snapshot DB (via `scripts/db-refresh-template.sh` flow), so newly cloned lane DBs are pre-switched.

## Verify after deploy

- Health endpoint green
- `/admin/` redirects to the Zitadel SSO login (unchanged) and an admin can log in
- API `/v1/` responds; Zitadel-issued tokens still validate
- In a shell: `get_user_model()._meta.label` → `accounts.User`, and user emails/pks match the pre-deploy list

## Rollback

Behavior-neutral release: rollback = previous image/commit, no env changes to undo. DB migrations are forward-only (the new `accounts_user` table + retargeted FKs are simply unused by old code — harmless).

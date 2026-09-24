# Claude Development Guide

Quick reference for Claude when working on wodore-backend.

**Note**: This file should be updated whenever important development information, patterns, or infrastructure details are discovered during work on the project.

## Essential Commands

Use `app` command with activated virtualenv (sets environment with infisical):

```bash
# Activate virtualenv first
source .venv/bin/activate

# Django commands (app alias uses infisical for environment)
app <command>

# Examples
app makemigrations
app migrate
app update_availability --all

# Note: app expands to: infisical run --env=dev --path /backend --silent --log-level warn -- app <command>
```

## Authentication Modes

Two feature flags (see `server/settings/components/oidc.py`):

| Mode | Flags | Admin login | Frontend/API auth |
|---|---|---|---|
| Zitadel (prod/staging default) | `OIDC_ENABLED=true` | OIDC SSO | Zitadel tokens (introspection) |
| Local (dev/test default) | `LOCAL_AUTH_ENABLED=true` | classic Django login (`app createsuperuser`) | built-in provider at `/oauth/local/` |

- `LOCAL_AUTH_ENABLED=true` is hard-refused outside `DJANGO_ENV=development|test`.
- OIDC enabled + provider unreachable = startup fails fast (`ImproperlyConfigured`).
- Frontend local mode: `WODORE_OICD_ISSUER_URL=http://localhost:8000/oauth/local`,
  `WODORE_OICD_CLIENT_ID=wodore-local-dev`, any `WODORE_OICD_RESOURCE_ID`.
- Local users: `app local_auth_users` (admin@local.test / admin-dev, editor@local.test / editor-dev).
- Test tokens: `POST /oauth/local/token` with `grant_type=password`.

## Project Structure

- **Django Apps**: `server/apps/` (e.g., `huts/`, `availbility/`, `organizations/`)
- **Settings**: `server/settings/components/` (modular settings files)
- **API**: Django Ninja (not DRF) - endpoints typically in `api.py`
- **Admin**: Django Unfold - configuration in `server/settings/components/unfold.py`

## Documentation

### Work In Progress

Document your work under `_work` in this form `yymmdd_working_title.md`. Keep the document up-to-date.

### API Documentation

OpenAPI schema available at:

- **Local**: <http://localhost:8000/v1/openapi.json>
- **Production**: <https://hub.wodore.com> (may not be up-to-date during development)

## Tech Stack

- **Framework**: Django with Django Ninja for API
- **Admin**: Django Unfold (customized admin interface) - [Documentation](https://unfoldadmin.com/docs/)
- **Database**: PostgreSQL with PostGIS
- **Dependencies**: hut-services library for external hut information and booking data
- **Secrets**: Infisical for environment variable management

### Local Editable Hut-Services

For local development, `hut-services` and `hut-services-private` can be installed as
editable sources from the sibling checkouts (see `[tool.uv.sources]` in `pyproject.toml`).
Switch **both** to path sources together (uv resolves the private package's
`../hut-services` path dependency and conflicts with a git pin), then run
`uv sync --extra private` — the `private` extra is required to install
`hut-services-private` at all (plain `uv sync` omits it).

## Related Projects

The Wodore ecosystem consists of multiple repositories:

- **Backend** (this repository): `wodore-backend/`
- **Frontend**: `../wodore-frontend-quasar/` - Quasar/Vue.js frontend application
- **Hut Services (Public)**: `../hut-services/` - Public library for hut information schemas and base services
- **Hut Services (Private)**: `../hut-services-private/` - Private implementations for external booking services (HRS, SAC, etc.)

All paths are relative to the repository root (`wodore-backend/`).

### WEPs (Wodore Enhancement Proposals)

Technical proposals for significant features and architectural decisions:

- **Location**: `docs/weps/board/` - Blog posts in MkDocs
- **Format**: Single-sentence summary + detailed analysis with categories/tags
- **Build**: `inv docs.serve` - Shows all WEPs with integrated TOC in left sidebar
- **Online Access**: `/weps/` (blog index), `/weps/tags/` (tags), `/weps/category/` (categories)

## Infrastructure

### Docker Compose Services

Services are defined in `docker-compose.yml`:

- **PostgreSQL Database (PostGIS)** - Port 5432
- **Imagor** (Image Processing) - Port 8079
- **Martin** (Vector Tile Server) - Port 8075
  - Serves vector tiles from PostGIS database
  - Configuration: `config/martin.yaml`
  - Endpoint: `http://localhost:8075/huts/{z}/{x}/{y}.pbf`
  - Catalog: `http://localhost:8075/catalog`
  - Currently serving: `huts` table (public and active huts only)
  - Properties: `slug`, `elevation`, `capacity_open`, `capacity_closed`, `hut_type_open_id`, `hut_type_closed_id`

## Common Patterns

### Models

- Use `TimeStampedModel` from `model_utils` for created/modified fields
- Custom managers in separate `managers.py` files
- Translation support with `gettext_lazy`

### Admin

- Inherit from `server.apps.manager.admin.ModelAdmin` (not Django's)
- Use `@display` decorator from `unfold.decorators` for custom displays
- Add apps to TABS in `server/settings/components/unfold.py` for tabbed navigation

### Managers

- Inherit from `server.core.managers.BaseManager`
- Define custom querysets for complex queries

### API Endpoints (Django Ninja)

**Documentation Style:**

- **Function docstring**: Keep it simple, usually one line describing what the endpoint does
- **Parameters**: Use `Query()` from `ninja` to add detailed descriptions for each parameter
- **Examples**: Only add examples if helpful (not for simple integers, bools, or obvious values). Use `example="value"` (singular), not `examples=[...]`
- **Response**: Set `exclude_unset=True` on the router decorator to exclude fields that are not set (avoids null fields in response)

**Key Points:**

- Use `Query(...)` for required parameters with description (NOT `Field()` - that's for Pydantic schemas)
- Use `Query(default_value, description=...)` for optional parameters
- Add `example="value"` only when it helps clarify usage (e.g., for search strings, special formats, or non-obvious numeric values)
- Skip examples for obvious types like simple integers, booleans, or enums (Swagger UI shows these well)
- `exclude_unset=True` works by not adding fields to the response dict when they shouldn't be included
- Don't set fields to `None` if you want them excluded - simply don't add them to the result dict
- Add detailed descriptions explaining what values mean, especially for numeric thresholds or enum options

## Testing

After making changes, **always run the test suite** to verify nothing is broken:

```bash
# Activate virtualenv first
source .venv/bin/activate

# Run all tests
inv tests
```

**Important**: This is mandatory after any code changes before considering work complete.

**In a worktree**: `inv tests` resolves `POSTGRES_DB=wodore` from
`.env.test` and would collide all lanes on one shared test database.
Use the lane runner instead (see § Worktrees / workz):

```bash
scripts/lane-run.sh .venv/bin/pytest
```

## Worktrees / workz

Agent worktrees are provisioned by [workz](https://github.com/rohansx/workz)
(see `.workz.toml`). Every worktree gets:

- **Dotfiles synced** from the main checkout: `.env*` (workz default) plus
  `.infisical.json` and `.geoplaces_osm_import.json`.
- **`.venv` symlinked** — shared virtualenv, never copied. Never `git add`
  the symlink or `.env.local` (both gitignored).
- **Its own database on the shared dev postgres** (`django-local-postgis:5432`,
  no extra ports), cloned from the quiescent `wodore_template` snapshot —
  same state as the dev main DB. Need current dev data? Refresh the template
  first: `scripts/db-refresh-template.sh` (takes a few minutes).
- **A dev-server port range** from 3400 up (only used by `workz run`).
- **`martin_sync/` copied** into every worktree (gitignored, ~109 MB,
  generated by `app martin_sync`; workz `copy_add` cannot copy directories,
  so the provisioning hook `scripts/sync-martin.sh` does). Refill the lane
  copy against the lane DB with
  `scripts/lane-run.sh .venv/bin/python manage.py martin_sync`.

**Run commands against the lane DB with the standard infisical wrapper, not
raw `infisical run`:**

```bash
scripts/lane-run.sh .venv/bin/pytest
```

`workz` writes the lane DB name into `.env.local`, but Django reads
`POSTGRES_DB` from the environment (infisical injects it) — `lane-run.sh`
re-injects the lane name after infisical so it wins. Teardown drops the lane
DB: `workz done <branch> --cleanup-db`.

**Lane step 1:** the global pi provisioning hook runs `workz sync …
--isolated`, which syncs files and allocates the DB name — but does **not**
run the `post_start` hook (that only fires on `workz start`). Create the
lane database yourself after provisioning:

```bash
scripts/lane-db.sh create && scripts/sync-martin.sh
# both idempotent: DB clones from wodore_template, martin_sync copies
# from the main checkout
```

Note: workz reads `.workz.toml` from the **main checkout** — provisioning
activates repo-wide once this file is merged to main (before that, a
temporary untracked copy in the main checkout bootstraps it).

**⚠ Martin/imagor rule:** work that touches **martin** or **imagor** must
**NOT be done in a worktree.** The shared martin/imagor containers keep
reading the *main dev database* — lane databases are invisible to them, so
martin/imagor changes (config, tile generation, image processing) can only
be validated from the main checkout.

**Martin version/image updates** (the `martin` service in
`docker-compose.yml`) are likewise done in the **main checkout**, never in
a worktree.

# wodore-backend Development Guide

Quick reference for agents and contributors working on wodore-backend.

**Note**: This file should be updated whenever important development
information, patterns, or infrastructure details are discovered during work
on the project.

## Essential Commands

Django commands run through the `app` wrapper (loads the environment via
Infisical):

```bash
source .venv/bin/activate    # activate virtualenv first

app makemigrations           # Django commands via app (uses Infisical env)
app migrate
app update_availability --all

inv tests                    # run the test suite — mandatory after any change
inv check.types              # pyrefly type check
inv lint                     # ruff lint + format check
```

- `app` expands to `infisical run --env=dev --path /backend -- app <command>`
  (no `--silent`: it swallows the child's stdout — interactive commands like
  `app createsuperuser` would hang with invisible prompts).
- Without Infisical, plain `.env` files work too:
  `uv run python manage.py <command>`.

## Environments & URLs

| Environment | API / OpenAPI | Frontend |
|---|---|---|
| Local | <http://localhost:8000/v1/openapi.json> | <http://localhost:9000> |
| Staging | <https://hub.stg.wodore.com> | <https://stg.wodore.com> |
| Production | <https://hub.wodore.com> | <https://wodore.com> |

- Deployed OpenAPI may lag during active development.
- API CDN hosts: `hub.cdn.wodore.com` / `hub.cdn.stg.wodore.com` (BunnyCDN);
  vector tiles: `tiles.wodore.com` / `tiles.stg.wodore.com`.
- Deployment lives in the burginfra repo (see Related Projects): new docker
  builds auto-update staging, production is a manual merge to `main`.

## Changelog & Pull Requests

Both changelogs are auto-generated on release — never edit them by hand and
never ship changelog entries inside PRs. Full conventions:
[CONTRIBUTING.md](CONTRIBUTING.md).

- PR titles are changelog-ready: imperative, capitalized, no
  conventional-commit tags (they land in `CHANGELOG.md` verbatim).
- Label every PR with a `type:*` label; API changes additionally get an
  `api:*` label and also appear in `CHANGELOG_API.md` (see API Versioning).
- CI quirk: workflow events sometimes don't fire for a branch — proactively
  merge `origin/main` before pushing, or recreate the PR from a fresh
  branch name. Prefer fresh branch names per PR.

- `CHANGELOG.md`: built by `inv release` from merged PR titles.
- `CHANGELOG_API.md`: regenerated from PRs labeled `api:*`.

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
- Local users: `app local_auth_users` (<admin@local.test> / admin-dev,
  <editor@local.test> / editor-dev).
- Test tokens: `POST /oauth/local/token` with `grant_type=password`,
  `client_id=wodore-local-dev-password`, `client_secret=wodore-local-dev-secret`
  (dev/test-only client seeded by `app local_auth_users`).

## Project Structure & Tech Stack

- **Framework**: Django with django-modern-rest (dmr, not DRF) for the API
- **Admin**: Django Unfold — [Documentation](https://unfoldadmin.com/docs/)
- **Database**: PostgreSQL with PostGIS
- **Django Apps**: `server/apps/` (e.g., `huts/`, `availability/`, `organizations/`)
- **Settings**: `server/settings/components/` (modular settings files)
- **API**: controllers in `api.py` modules, each exporting a `paths` list
- **Secrets**: Infisical or `.env` files for environment variables
- **Dependencies**: `hut-services` library for external hut information and
  booking data

## Documentation

### Work In Progress

Local working notes go under `_work/` (git-ignored), named
`yymmdd_working_title.md`. Keep the document up to date while working.

### Translations (gettext)

`LOCALE_PATHS = ("locale/",)` holds the gettext catalogs; `LANGUAGE_CODE`
is `de`, `settings.LANGUAGES` (de/en/fr/it) is the canonical language
list. `.mo` files are gitignored: run `app compilemessages` (needs
`gettext`) after pulling/changing `.po` files — CI and the docker image
build compile them automatically. Regenerate msgids with
`app makemessages -l <lang>`; the per-language `/llms.<lang>.txt`
variants render through these catalogs (`{% translate %}` in
`server/templates/txt/llms.txt`, locale active per URL — see
`server/apps/main/views.py`).

### WEPs (Wodore Enhancement Proposals)

Technical proposals for significant features and architectural decisions:

- **Location**: `docs/weps/board/` — blog posts in MkDocs
- **Format**: single-sentence summary + detailed analysis with categories/tags
- **Build**: `inv docs.serve` — shows all WEPs with integrated TOC
- **Online**: `/weps/` (index), `/weps/tags/`, `/weps/category/`

## Related Projects

The Wodore ecosystem:

- **Backend** (this repository): `$REPO_WODORE_BACKEND`
- **Frontend**: `$REPO_WODORE_FRONTEND` — Quasar/Vue.js application
- **Hut Services (public)**: `$REPO_WODORE_HUT_SERVICE` — schemas and base
  services for external hut information
- **Hut Services (private)**: `$REPO_WODORE_HUT_SERVICE_PRIVATE` — external
  booking service implementations (HRS, SAC, …)
- **BurgInfra (deployment)**: `$REPO_BURGINFRA` — production and staging
  deployment; new docker builds auto-update staging, production needs a
  manual merge to `main`

### Local Editable Hut-Services

For local development, `hut-services` and `hut-services-private` can be
installed as editable sources from the sibling checkouts (see
`[tool.uv.sources]` in `pyproject.toml`). Switch **both** to path sources
together (uv resolves the private package's `../hut-services` path
dependency and conflicts with a git pin), then run `uv sync --extra
private` — the `private` extra is required to install `hut-services-private`
at all (plain `uv sync` omits it).

## Infrastructure

### Docker Compose Services (dev only)

Defined in `docker-compose.yml` — development only, never used in production:

- **PostgreSQL (PostGIS)** — port 5432
- **Imagor** (image processing) — port 8079
- **Martin** (vector tile server) + **tile-router** (nginx) — port 8075
- **MapProxy raster facades** — port 8091

### Tiles (Martin + tile-router + MapProxy)

- **Martin** serves vector tiles from PostGIS; configuration
  `martin_sync/config/martin.yaml` is generated by `app martin_sync`
  (Martin loads its config at startup — restart to pick up changes).
  Endpoints: `http://localhost:8075/huts/{z}/{x}/{y}.pbf`,
  catalog at `/catalog`. DB sources: `huts` (public+active huts),
  `geoplaces_view`, `geoplaces`, `availability` (params `date`/`days`/
  `days_max_zoom`/`cache_ttl`, see `server/apps/availability/tiles.py`).
- **Tile-router** (`tile_server/tile-router.conf.template`, nginx) is the
  single tile origin: `/raster/*` → MapProxy facades, `*.mlt` → Martin with
  MLT accept header, everything else → Martin. `MARTIN_TILE_URL` (default
  `http://localhost:8075`) points here. 7d immutable browser caching; the
  styles' `?v=N` param busts. It also derives Bunny CDN purge tags from the
  URL automatically — new sources/facades are purgeable with no nginx edit
  (see the template comments).
- **MLT (MapLibre Tile) v1**: any source is also served as MLT on the
  explicit `.mlt` URL space (serve-time conversion, implicit on
  Martin ≥ 1.16). Only the literal `.mlt` suffix selects MLT — extension-less
  /`.pbf`/`.mvt` stay MVT. Opt-in is style-side (`encoding: mlt` + `.mlt`
  tiles template). Source ids must be underscore-only (hyphens break MLT
  serving and purge tagging).
- **MapProxy facades** (`tile_server/mapproxy/`): `world_topo`
  (OpenTopoMap + basemap.at + swisstopo) and `world_satellite` (ESRI), both
  served as WebP. Styles reference them via implementation-agnostic
  `/raster/tiles/...` paths. See `tile_server/mapproxy/README.md` for the
  WebP recipe and the single-source passthrough gotcha.
- **Terrain postprocessing** (Martin ≥ 1.16): `contours` (server-traced MVT
  contour lines from Mapterhorn) and `hillshade` (baked raster PNG from AWS
  Terrain Tiles). Martin caches only upstream elevation tiles, not the
  postprocessed output. Test style: `wd-terrain-test`
  (`tile_server/styles/wd-terrain-test.json`).
- **Transitland passthrough** (`transitland_stops`): Martin proxies the
  Transitland v2 stops tileset with a server-side `apikey` header baked in
  by `martin_sync` (`TRANSITLAND_API_KEY` from the env registry) — the key
  never appears in a client-visible URL.

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

### API Endpoints (dmr Controllers)

- One `Controller[...]` class per path (subclass
  `server.apps.api.controller.ApiController`); method per HTTP verb
  (`def get(...)`, `def post(...)`); docstring = description, endpoint
  slug = title
- Typed components: `parsed_query: Query[YourQueryModel]`,
  `parsed_body: Body[X]`, `parsed_path: Path[X]` (parameter names MUST be
  `parsed_*` — dmr silently skips others)
- Query/path models are plain pydantic models composed from
  `LanguageQuery` / `FieldsQuery` (`server.apps.translations.schema`,
  `server.apps.api.query`); descriptions via `Field(..., description=...)`,
  examples via `json_schema_extra={'example': ...}`
- **Every route sets `name=` on `dmr.routing.path` equal to
  `@modify(operation_id=...)`** (versioning keys on it; startup checks
  E003/E004 enforce the invariant)
- Response headers (Cache-Control etc.) via `@modify(headers=cache_headers(max_age=...))`
- Errors: `raise_not_found(...)`, `APIError({'code', 'detail'}, status_code=...)`
  — one error contract everywhere
- Serialization: `WodoreSerializer` dumps with `exclude_unset` — construct
  minimal DTOs/dicts, unset optional fields are absent from the JSON (not
  null). Keep that when adding fields
- Endpoints returning `HttpResponse` (ETag/304 paths) use
  `@validate(ResponseSpec(...))` + `self.to_response(...)`

## API Versioning

The API (`/v1/`) uses date-based contract versioning (`Api-Version` header /
`api_version` query param). Registry:
`server/apps/apiversions/registry.py`. Full runbook:
[docs/api-versioning.md](docs/api-versioning.md) and
[CONTRIBUTING.md](CONTRIBUTING.md). The rules that matter for any code change:

- **Versions are created only for breaking changes** (remove/rename, new
  required param, tightened validation, changed observable defaults, new
  response enum value). Additive changes need no version. Litmus test:
  would a client pinned to the current version behave differently after
  the deploy?
- **Breaking change PR** = new `VersionChange` (downgrade transforms keyed
  by `operation_id` — explicit ids required, system check enforces) +
  snapshot via `app api_snapshot` **committed in the PR** (CI checks
  presence) + contract tests + labels `type:*` and `api:breaking`.
- **At most one unreleased version**: if the current version has no
  `api/<date>` tag yet, amend its `VersionChange` (merge transforms, keep
  date, regenerate snapshot) — never stack a new version. CI gates this
  (`python3 -m server.apps.apiversions.registry_check`).
- **Release**: CI cuts the `api/<date>` tag when the docker build shipping
  it succeeds; `inv release` regenerates both changelogs.
- Response downgrades for pinned-old versions are applied by
  `ApiVersionMiddleware` uniformly to every JSON response (dmr controllers
  and GeoJSON endpoints alike); contract tests pin this. ETags on hut
  endpoints key on the resolved version + registry hash.

## Type Checking

Type checking is **pyrefly** — one engine for CLI, CI and editor LSP,
running `preset = "strict"` project-wide. django-stubs provides the Django
type vocabulary.

```bash
inv check.types        # or: uv run pyrefly check
```

**Rules & quirks** (hard-won, follow them):

- All new/changed code must be fully annotated — the implicit-any rules are
  on everywhere. Fix findings in code; there is **no baseline** and
  creating one is not an option.
- Suppressions are a last resort: bare `# type: ignore  # <short reason>`.
  Never `# pyright:` comments. For multi-line expressions pyrefly cannot
  suppress line-based — restructure to a single-line anchor (typed local,
  constant) and suppress that line.
- Established idioms: modeltrans `<field>_i18n: str` annotations ·
  `Manager.from_queryset(QuerySet)` factory (+ its one documented chain
  gap) · split-settings cross-file `# type: ignore` · `@override` from
  `typing` · django-stubs signatures for management commands
  (`add_arguments(parser: CommandParser)`, `handle(*args: Any, **options: Any)`)
  and admin hooks.
- Don't gate on ty (Astral): it has no Django support (many false
  positives here); revisit when astral-sh/ty#1018 lands.

## Testing

After making changes, **always run the test suite** to verify nothing is
broken — mandatory before considering work complete:

```bash
inv tests
```

**In a worktree**: use the lane runner instead (see § Worktrees / workz):

```bash
scripts/lane-run.sh .venv/bin/pytest
```

## Worktrees / workz

Agent worktrees are provisioned by [workz](https://github.com/rohansx/workz)
(see `.workz.toml`). Every worktree ("lane") gets:

- **Its own `.venv`** (never symlinked; synced with `--extra private` —
  plain `uv sync` silently omits hut-services-private)
- **Its own database** on the shared dev postgres, cloned from the
  quiescent `wodore_template` snapshot
- **A dev-server port** (range from 3400 up) and a **`martin_sync/` copy**

**Lane setup** (idempotent — lane venv, lane DB, martin_sync copy):

```bash
scripts/lane-setup.sh
```

**Run commands against the lane DB** with the standard wrapper, never raw
`infisical run` (the lane DB name in `.env.local` must win over the
infisical-injected one):

```bash
scripts/lane-run.sh .venv/bin/pytest
```

**Dev server**: `scripts/lane-dev.sh fg|start|stop|status|attach|kill` —
runserver plus a django-q2 qcluster, guarded so the qcluster is torn down
when runserver stops. `QCLUSTER=0` disables the qcluster.
**Teardown**: `scripts/lane-teardown.sh` (dev server → martin → lane DB,
idempotent).

After `source .venv/bin/activate` in the lane, `app <command>` runs against
the **lane** database (the main checkout's `app` targets dev).

**Rules:**

- **Never run `docker compose` against the shared dev stack from a
  worktree** — the compose bind-mounts are relative, so a worktree run
  repoints the shared containers at the worktree's copies (an empty pgdata
  makes the dev database appear "wiped"). Use the lane scripts; run
  `docker compose` only in the main checkout.
- Tile work *can* happen in a worktree: `scripts/lane-martin.sh start`
  runs a lane-scoped martin + tile-router serving the lane DB on the lane
  port (`lane-run.sh` points `MARTIN_TILE_URL` there automatically).
  Work on the **shared** martin instance (image updates, shared config)
  stays in the **main checkout**.
- Work touching **imagor** is done in the main checkout — the shared
  container reads the main checkout's media setup.

### Error Tracking (Sentry protocol)

`sentry-sdk` initialized in `server/settings/components/sentry.py`,
included FIRST in the settings list (before logging config). Rules:

- **DSN-gated**: no `SENTRY_DSN` env var → SDK never initializes
  (dev/test/CI are always telemetry-free). Staging/prod get the DSN from
  Infisical.
- **Vendor-neutral**: the DSN decides the destination — sentry.io or Better
  Stack (Sentry-SDK-compatible ingestion). Switching vendors = swap DSN,
  never a code change. Rollback = unset the DSN.
- **Release = `GIT_HASH`** (per-commit deploys) in both staging and prod;
  package semver rides along as an `app_version` event tag.
- **`SENTRY_TRACES_SAMPLE_RATE`** (default 0.05, `0` = errors-only) —
  health checks are never traced (sampler excludes `/health/`).
- **PII stays off**: `send_default_pii=False` is fixed — do not flip
  without a privacy review. Caveat: this only covers SDK-attached data —
  PII that app code writes *into log messages* still flows into
  breadcrumbs and error events; keep tokens/emails out of log calls.
- **django-q2 failures** reach Sentry via the in-repo error reporter
  (`server/core/q2_sentry.py`, wired through `Q_CLUSTER["error_reporter"]`)
  — q2 itself swallows task exceptions.

### Map Layers (basemaps app)

Overlays and basemaps live in `server/apps/basemaps`: `MapLayer` rows
(role basemap|overlay; `(slug, spec, profile)` variants — `full` complete
MapLibre styles vs `subset`, the strict Leaflet-renderable whitelist in
`server/apps/basemaps/validation.py`; `version` records the rules a row
was validated against), parameters (scalar + `opacity-curve` widgets,
`{{token}}` nodes in styles), category links, coverage.

Serving: `GET /v1/map/catalog` (dmr) and `GET /v1/map/styles/{slug}.json`
(plain view; `?mode=tokenized`, `?spec=`, `?profile=full|subset` — omitted
stays profile-agnostic; subset clients never receive full variants).

**Style validation flow** (full detail:
[docs/map-style-subset-spec.md](docs/map-style-subset-spec.md)):

- **Saves** gate in `MapLayer.clean()`: structural + parameter-token
  checks → subset walker (`profile=subset` rows) → styl as a subprocess
  when a binary is on PATH (absent = silent skip). E-codes block unless
  listed in the row's `styl_ignored_rules` (JSON codes, `["*"]` skips
  styl entirely — external-derived styles); W-codes never block.
- **Seed** (`map_seed`): the upsert calls the walker + styl directly
  (update_or_create bypasses clean()); external-derived rows carry
  `styl_ignored_rules: ["*"]`. New subset rows are tagged manually in
  `map_seed` — never auto-tagged.
- **CI**: `validate_map_styles` sweep in the tests job + the
  `map-style-spec` job (styl over `dump_map_styles` output +
  `fixtures/styles/`).

Caching: layer entries carry `style_version` (appended to `style_url` as
`&v=`) — a matching `?v=` serves immutable (1 y); unversioned fetches allow
the CDN edge 60 s of staleness. Volatile-parameter clocks (runtime `date`)
rotate every derived cache key — see `server/apps/basemaps/api.py` module
docstring. `martin_sync` serves tiles/sprites/fonts only — styles are
served by the API from the registry.

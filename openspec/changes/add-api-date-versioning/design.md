# Design: add-api-date-versioning

## Context

Verified against the codebase (django-ninja 1.6.x pinned, installed and inspected):

- Single `NinjaAPI` at `/v1/` in `server/apps/api/api_v1.py`, already with custom
  `MsgSpecParser`/`MsgSpecRenderer` (msgspec-based). Routers from ~10 apps are mounted
  there; ~54 router operations, of which ~37 have explicit `operation_id` (the rest get
  ninja's auto-generated id from the function name).
- **`NinjaAPI.create_response` receives `(request, data, status, temporal_response)` —
  no operation/operationId** (verified in installed ninja 1.6). It cannot key transforms
  by operation on its own.
- **Two endpoints bypass the Ninja response flow entirely**: `get_huts_geojson`
  (`server/apps/huts/api/_hut.py`) and `get_hut_availability_geojson`
  (`server/apps/availability/api.py`) do `response.write(msgspec.json.encode(geojson))`
  and return the response directly (deliberate: DB→dict→bytes with no pydantic
  re-validation). A renderer/create_response hook never sees their data.
- `get_huts_geojson` sets ETag/Last-Modified from DB state + an explicit
  `additional_keys` list of query params (`server/apps/huts/api/etag_utils.py`); the
  availability endpoint sets `Cache-Control: max-age=600`. Version-dependent responses
  must not be cached or 304'd across versions.
- `/v1/version` exists in `server/apps/utils/api.py` with `hash`, `hash_long`,
  `version`, `timestamp`, `environment` (pydantic `VersionSchema`).
- SVG redirects (`server/apps/symbols/api.py` `get_symbol_svg`) return
  `HttpResponseRedirect`; `/v1/huts/bookings*` are already OpenAPI `deprecated=True`
  with no sunset date.
- CORS via django-cors-headers; `CORS_ALLOW_HEADERS = [*default_headers,
  "access-control-allow-origin"]`; `CORS_EXPOSE_HEADERS` not set yet. Custom Django
  middleware precedent exists (`server/middleware/headers.py`).
- git-cliff with `github.pr_labels` commit parsers works today (`cliff.toml`,
  `tag_pattern = "^v[0-9]+\.[0-9]+\.[0-9]+"`), labels `type:*`/`BREAKING`.
- No streaming (`AsyncIterator`) responses in the API today; ninja 1.6 supports them.
- Consumers: Capacitor mobile app (months-lived installs), Quasar web frontend,
  MapLibre tile/feature clients. `Deprecation` header is RFC 9745
  (structured-field date `@<unix-seconds>`); `Sunset` is RFC 8594 (HTTP-date).

## Goals / Non-Goals

**Goals:**

- Decouple app releases from backend releases; one codebase, newest logic only.
- Warn-then-block lifecycle for old versions; concrete sunset for the deprecated
  bookings endpoints.
- Exact per-version OpenAPI documentation; contract tests prove transforms.
- Minimal dependencies; extension points that survive ninja upgrades.

**Non-Goals:**

- Per-account version pinning; `/v2/`; automatic transform generation from schema diffs;
  versioning SVG redirects, `/v1/version`, openapi.json and docs; frontend/mobile
  implementation (separate changes in the app repos); request-upgrade transforms beyond
  registry shape + hook (no production use yet — deferred to the first breaking change
  that needs one).

## Decisions

### D1: Version identifiers
Calendar dates `YYYY-MM-DD`, compared lexically. A new version is created only for
breaking changes. Additive changes (new endpoints, optional fields/params) ship without
a new version. **Initial version = rollout date**, set in the registry when this change
is released (snapshot + `api/<date>` tag cut at release time).

### D2: Version resolution
Precedence: `Api-Version` header → `api_version` query parameter → latest.
Equal header and query value: allowed. Different values: `400`
`{"code": "api_version_conflict", ...}` (strict; catches client bugs early).
Unknown/invalid date: `400` `{"code": "api_version_invalid", ...}`.
Resolved version is stored on `request.api_version` and echoed as `Api-Version`
response header. Ninja ignores unknown query params, so `api_version` does not clash
with existing `Query[...]` schemas.

### D3: Scope
Applies to all Ninja operations under `/v1/` that return a body, including `.geojson`
operations. Explicitly excluded (via an exclusion list in the registry, not path regex):
SVG redirects, `/v1/version`, `/v1/openapi.json`, `/v1/docs`, and future streaming
operations. Excluded operations never raise version errors and never get version headers
beyond nothing.

### D4: Registry and transforms
New Django app `server/apps/apiversions/` (INSTALLED_APPS, needed for the management
command). `apiversions/registry.py` holds `VersionChange` entries:

```python
VersionChange(
    version="2027-03-01",
    description="Hut: `capacity_open`/`capacity_closed` moved into `capacity`.",
    responses={
        "get_hut": downgrade_hut_capacity,
        "get_huts": each(downgrade_hut_capacity),
    },  # keyed by operationId
    requests={},  # upgrades, deferred
)
```

- Request upgrades apply oldest → newest; response downgrades newest → oldest, down to
  the client version. Transforms MUST be defensive (`pop(key, None)`, rename only when
  present, tolerate `null`, tolerate fields dropped by `include`/`exclude`/`embed_*`).
- Shared helpers for lists and GeoJSON `features[*].properties`.
- **Registry integrity check** at startup (Django system check + test): every
  operationId referenced by any `VersionChange` must resolve against
  `api.get_openapi_schema()` — fails fast on typos and on silent renames of
  auto-generated ids. Endpoints gaining a transform must have an explicit
  `operation_id`.

### D5: Hook architecture (hybrid) — revised after codebase verification
`create_response` is unusable as primary hook (no operationId, and two endpoints bypass
it entirely). Instead:

1. **`VersionedRenderer(MsgSpecRenderer)`**: `render(request, data, response_status)`
   receives serialized Python data — the right shape for transforms. The renderer reads
   `request.api_version` and the operation id stashed by (2). Replaces `MsgSpecRenderer`
   in `NinjaAPI(...)`.
2. **Operation wrapping**: after all `add_router` calls in `api_v1.py`, a small
   `apiversions.wrap_api(api)` helper walks the mounted routers' `path_operations` and
   wraps each `operation.run` so `request.ninja_operation = operation` is set before the
   original runs (the same wrapping pattern ninja's own router decorators use —
   `router.py::_apply_decorators_to_operations`). Zero transforms registered → wrapper
   is a pass-through setting one attribute.
3. **Direct-write endpoints** (`get_huts_geojson`, `get_hut_availability_geojson`):
   call `apiversions.apply_response_transforms(request, "get_huts_geojson", geojson)`
   explicitly before `msgspec.json.encode(...)`. Keeps the deliberate DB→dict→bytes
   fast path. A contract test proves both endpoints honor a test-only `VersionChange`,
   so they can never silently escape versioning.
4. **Thin Django middleware** (`apiversions/middleware.py`): version resolution (D2),
   conflict/invalid 400s, sunset 410s, `Api-Version` echo, `Deprecation`/`Sunset`/`Link`
   headers, `Vary: Api-Version`. Never parses response bodies. Placed after
   `CorsMiddleware` (CORS stays outermost so error responses keep CORS headers).

### D6: Lifecycle
- Minimum deprecation period: **6 months** between a version's deprecation and its
  sunset (each `VersionChange`/version entry stores its own `sunset` date; policy
  enforced in review, not code).
- Headers: `Deprecation: @<unix-seconds>` (RFC 9745), `Sunset: <HTTP-date>` (RFC 8594),
  `Link: <CHANGELOG_API anchor>; rel="deprecation"`.
- Past sunset version → `410` `{"code": "api_version_sunset", "version": ...}`.
- **Endpoint-level deprecation** uses the same headers: `/v1/huts/bookings` and
  `/v1/huts/bookings.geojson` get a concrete sunset = 6 months after this change's
  rollout (openAPI `deprecated: true` already set). Sunset date lives in the registry so
  `/v1/version` can expose it.

### D7: `/v1/version` extension (additive)
Add optional `api` block to `VersionSchema`: `current` (newest registry version),
`default` (what unpinned clients get — equals `current` initially, distinct only if a
staged rollout pins it back), `supported` list of `{version, status: current|default|
deprecated|sunset, sunset?}`. Existing fields unchanged.

### D8: OpenAPI snapshots & docs
- Live `/v1/openapi.json` always describes the current version; `info.version` = current
  API version date. `Api-Version` and `api_version` documented globally.
- `manage.py api_snapshot` writes `server/apps/apiversions/openapi/<version>.json`
  (committed).
- `/v1/openapi.json?api_version=<v>` serves the stored snapshot for supported versions.
- Docs: ninja's Swagger template hardcodes a single schema URL — no native top-bar
  `urls` dropdown. Implement a **simple version switcher**: `/v1/docs` page lists
  supported versions as links (`?api_version=`), each loading the matching schema
  (custom thin docs view or Swagger settings override — implementer's latitude, the
  requirement is that all supported versions are reachable from the docs UI).

### D9: Contract tests (scoped)
For each supported non-current version: exercise **the operations that have registered
transforms** against real test data, apply that version, validate the response against
the version's snapshot schema (`openapi-core` or jsonschema over `components.schemas`).
Untransformed operations are covered by the snapshot drift guard (optional CI:
`oasdiff breaking <latest-snapshot> <live>` fails without a new `VersionChange`) —
not by an exhaustive 54-op × N-version matrix.

### D10: Changelogs
- `CHANGELOG_API.md` from `cliff-api.toml`: `tag_pattern = "^api/[0-9]{4}-[0-9]{2}-[0-9]{2}"`,
  `commit_parsers` on `github.pr_labels` (field name verified against the working
  `cliff.toml`): `api:breaking`, `api:added`, `api:deprecated`, `api:fixed`. Non-breaking
  API entries between API tags land under a "Live in all versions" heading.
- `VersionChange.description` must match its `api:breaking` changelog entry.

## Resolved questions (were open in the source spec)

- Q1 strict 400 on conflict: **yes** (equal values allowed). Q2 minimum deprecation:
  **6 months**. Q3 initial version: **rollout date**. Q4 bookings sunset: **yes, 6
  months after rollout**. Q5 non-breaking changelog layout: **"Live in all versions"
  block**.

## Risks / Trade-offs

- [Transform bugs corrupt old-client responses] → contract tests against snapshots; defensive transform rules (D4).
- [Unpinned clients get breaking changes on latest] → documented; unpinned requests logged/counted via middleware (structured log field), so adoption is measurable before the first breaking change.
- [Snapshot drift] → release checklist + CI check that the current registry version has a snapshot.
- [Ninja internals: `operation.run` wrapping] → same mechanism as ninja's own router decorators; isolated in `apiversions.wrap_api`; upgrade test in suite.
- [Direct-write endpoints escape versioning] → explicit helper + contract test proving both honor transforms (D5.3).
- [Wrong 304s across versions] → resolved version joins ETag key material (`additional_keys` + registry hash) and `Vary: Api-Version` (D11 below).

### D11: Caching correctness
- Responses resolved from the header carry `Vary: Api-Version`. Query-resolved ones differ by URL.
- `huts.geojson` ETag key material gains the resolved version (and a registry content
  hash, so registering a new transform changes the ETag even before data changes).
- `Cache-Control` values on geojson endpoints unchanged; `Vary` composes with them.

## Migration Plan

1. Ship this change: registry with the single initial version (rollout date), zero
   transforms, resolution + headers + discovery + snapshot infra + bookings sunset
   date. All clients are effectively on the initial version.
2. Release: `api_snapshot` + commit + tag `api/<date>` + generate `CHANGELOG_API.md`.
3. App starts sending `Api-Version` (frontend repos, separate changes).
4. First breaking change follows the documented workflow (new `VersionChange` +
   snapshot + `api:breaking` label).
5. Rollback: removing the middleware/renderer wiring restores current behavior; no data
   migration involved.

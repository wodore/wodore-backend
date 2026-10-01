# Tasks: add-api-date-versioning

## 1. App scaffold and registry

- [ ] 1.1 Create Django app `server/apps/apiversions/` (INSTALLED_APPS): `registry.py` with `VersionChange` (version, description, responses, requests, sunset), version list (initial version = release date, set at rollout), registry content hash, and the explicit exclusion list (SVG redirects, `/v1/version`, openapi.json, docs)
- [ ] 1.2 Registry integrity system check: every referenced operationId resolves against `api.get_openapi_schema()`; verify it catches a typo and an auto-id rename (test)
- [ ] 1.3 Transform helpers: `each()` for lists, `properties()` for GeoJSON `features[*].properties`, chaining newest→oldest over changes newer than the requested version; defensive-pop rules documented in docstrings

## 2. Resolution and lifecycle

- [ ] 2.1 Middleware `apiversions/middleware.py`: resolve header → query → latest; equal values OK; conflict → 400 `api_version_conflict`; unknown → 400 `api_version_invalid`; sunset → 410 `api_version_sunset`; stash `request.api_version`; skip excluded operations; register after `CorsMiddleware` in `server/settings/components/common.py`
- [ ] 2.2 Response headers on the same middleware: `Api-Version` echo, `Deprecation: @<unix>` (RFC 9745) + `Sunset: <HTTP-date>` (RFC 8594) + `Link; rel="deprecation"` for deprecated versions, `Vary: Api-Version` for header-resolved responses
- [ ] 2.3 CORS: add `Api-Version` to `CORS_ALLOW_HEADERS`; set `CORS_EXPOSE_HEADERS` with `Api-Version`, `Deprecation`, `Sunset`, `Link`
- [ ] 2.4 Unpinned-request logging: structured log field (or metric) when no version was given

## 3. Hooks and transforms

- [ ] 3.1 `VersionedRenderer(MsgSpecRenderer)`: apply response downgrades in `render()` using `request.api_version` + stashed operation id; no registered transforms → byte-identical behavior
- [ ] 3.2 `apiversions.wrap_api(api)` after the `add_router` calls in `server/apps/api/api_v1.py`: wrap each `operation.run` to stash `request.ninja_operation` (same pattern as ninja router decorators)
- [ ] 3.3 Call `apply_response_transforms(request, "<op_id>", geojson)` explicitly in `get_huts_geojson` (`server/apps/huts/api/_hut.py`) and `get_hut_availability_geojson` (`server/apps/availability/api.py`) before `msgspec.json.encode`
- [ ] 3.4 ETag keying: add resolved version + registry content hash to `huts.geojson` ETag key material (`additional_keys` / `etag_utils`); confirm `Vary` composes with existing `Cache-Control`
- [ ] 3.5 Test-only `VersionChange` proving chaining (two stacked downgrades) and direct-write coverage end-to-end; keep it out of the production registry

## 4. Discovery and docs

- [ ] 4.1 Extend `VersionSchema`/`get_version` (`server/apps/utils/api.py`) with the additive `api` block: `current`, `default`, `supported[{version, status, sunset?}]`
- [ ] 4.2 Document `Api-Version` + `api_version` globally in the live schema; set `info.version` to the current API version date
- [ ] 4.3 `manage.py api_snapshot` writing `server/apps/apiversions/openapi/<version>.json`; cut the initial snapshot for the rollout version
- [ ] 4.4 Serve snapshots via `/v1/openapi.json?api_version=`; docs version switcher reaching every supported version (simple links/custom view — ninja's Swagger template has no native dropdown)

## 5. Tests and CI

- [ ] 5.1 Unit tests: resolution precedence, agree/conflict/invalid, deprecated/sunset headers, exclusions (SVG, version, docs), CORS allow/expose, Vary, 410 bodies
- [ ] 5.2 Contract tests: for each supported non-current version, operations with registered transforms validated against that version's snapshot (both GeoJSON direct-write ops included)
- [ ] 5.3 CI: fail when the current registry version lacks a snapshot; optional `oasdiff breaking` guard; optional `api:breaking` label ↔ registry entry check
- [ ] 5.4 Full suite green: `scripts/lane-run.sh .venv/bin/pytest` in a lane

## 6. Changelog, bookings sunset, docs

- [ ] 6.1 `cliff-api.toml`: `tag_pattern = "^api/[0-9]{4}-[0-9]{2}-[0-9]{2}"`, `github.pr_labels` parsers for `api:breaking|added|deprecated|fixed`, "Live in all versions" block; generate the initial `API_CHANGELOG.md`
- [ ] 6.2 Create GitHub labels `api:breaking`, `api:added`, `api:deprecated`, `api:fixed`
- [ ] 6.3 Bookings sunset: register `/v1/huts/bookings` and `/v1/huts/bookings.geojson` sunset = 6 months after rollout; emit `Deprecation`/`Sunset` headers there; expose in `/v1/version`
- [ ] 6.4 README/docs: "Introducing a breaking change", "Releasing an API version", "Sunsetting a version" runbooks

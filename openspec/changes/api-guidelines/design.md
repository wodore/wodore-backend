## Context

The `/v1/` API is hand-rolled on django-modern-rest (dmr) controllers: one
`Controller` class per path, typed pydantic query/body models, a shared
`ApiController`, and a uniform `{code, detail}` error body raised via
`APIError` / `raise_not_found`. Conventions grew organically per lane:
`LanguageQuery` and `SparseFieldsQuery` centralize narrowing, ETag utilities
(`server/apps/huts/api/etag_utils.py`) implement the DB-aggregate revalidation
dance, and the basemaps app added envelope responses (`{"slots": [...],
"layers": [...]}`), served-value reporting (`X-Map-Spec`), and a style cache
keyed on `modified`. But nothing documents which parts are contract and which
were one-off decisions, so recent lanes already drifted: two overlapping map
catalog endpoints (`/v1/map/catalog`, `/v1/map/config`), 6-hour `cache_page`
windows over DB-tracked data, and field naming inconsistency (`version`
holding a row's `modified` timestamp). Date-based contract versioning
(`docs/api-versioning.md`) pins old shapes but says nothing about what new
shapes should look like.

## Goals / Non-Goals

- Goals: one canonical, long-form reference (`docs/api-guidelines.md`) for how
  Wodore API endpoints are shaped; the same rules captured as the
  `api-conventions` capability spec so future changes extend them deliberately;
  every rule mechanically checkable in review.
- Non-Goals: no code changes; no migration of existing endpoints; no adoption
  of JSON:API, OData, or any external API specification; no new enforcement
  tooling in this change (recorded as future apply-phase work instead).

## Decisions

### D1: Guidelines as documentation + spec, zero code — grandfathering

The standard applies to endpoints **created or meaningfully modified** after
this change. Existing endpoints are grandfathered until touched. Alternatives
rejected: (a) migrating existing payloads now — every reshape (the `GET
/v1/huts` bare top-level array, merging the two map catalogs) is a breaking
change requiring a `VersionChange`, transforms, and frontend coordination, for
zero client-visible gain; (b) rules as lint rules only — no lint covers
"meaningfully modified", and semantics (which tier of caching applies) need
prose anyway.

### D2: House standard, not an adopted external specification

We deliberately do **not** adopt JSON:API (or OData, or full REST-level
HATEOAS):

- The API is hand-rolled on dmr controllers; JSON:API is a framework-shaped
  spec (its media type, `data`/`attributes` nesting, `relationships`/
  `included` graph) that we would have to emulate manually everywhere — the
  parts dmr + generated OpenAPI TS clients already solve (typed schemas,
  predictable field names, nesting under our control) are exactly what
  JSON:API standardizes.
- Predictability for the frontend comes from the generated OpenAPI TypeScript
  clients — the schema *is* the contract; a second meta-format on top adds
  ceremony without adding information.
- Large parts of the surface are externally-spec'd formats we must not wrap:
  GeoJSON feature collections (`/v1/huts.geojson`), MapLibre
  `StyleSpecification` documents (`/v1/map/styles/{slug}.json`), Martin-shaped
  catalogs. JSON:API envelopes around them would be noise.
- We already cherry-picked the ideas worth having: sparse fieldsets
  (`fields[TYPE]`), typed error codes, content-versioned caching. Migrating to
  the full spec would break every client for no new capability.

### D3: Collections get an envelope; singletons are bare

Collection responses return an object keyed by the resource name
(`{"layers": [...]}`, `{"huts": [...]}`), never a bare top-level array;
singleton responses return the bare resource object (`GET /v1/huts/{slug}`
returns the hut; `GET /v1/map/styles/{slug}.json` returns the style document).

Why the envelope (vs. bare arrays, which are marginally simpler):

- **Extensibility**: `count`, pagination links, deprecation metadata, or
  `{"slots": [...]}`-style sibling sections can be added additively; a bare
  array cannot grow new top-level members without breaking clients that
  expect an array.
- **Industry precedent**: JSON:API, the Zalando REST guidelines, and the
  Microsoft REST API guidelines all require an object as the top-level
  collection shape — client tooling and reviewers pattern-match on it.
- **JSON-hijacking heritage**: the original motivation for the industry
  convention — array-topped JSON could be probed via `<script>` tag
  overrides of `Array`/`Object` constructors in legacy browsers. The attack
  is historical, but the convention it produced is durable and costs nothing.

Singletons stay bare because wrapping (`{"hut": {...}}`) adds a level of
nesting for exactly one element and no extensibility the resource's own
additive fields don't already provide.

### D4: One error contract, additive problem-details later

Every error is `{"code": "<ErrorCode>", "detail": "…"}` — `code` is a
machine-readable enum value (one per HTTP behavioral class the client acts on
differently, `server/apps/api/error_codes.py`), `detail` is the
human-readable specific reason. Raised exclusively via `APIError({...},
status_code=…)` / `raise_not_found(...)` so dmr renders the shape uniformly;
plain views reuse the same body (see `_style_error` in the basemaps app).
RFC 9457 problem-details alignment (additive `type`/`title`/`status`/
`instance`) is specced in the separate `error-api-problem-details` openspec
change; until it lands, no parallel error formats.

### D5: Slugs for identity, `modified` for content version

Public identifiers are slugs — stable, human-readable, never PKs. Content
versions are the row's `modified` timestamp (ISO 8601 UTC, from
`TimeStampedModel`), exposed under the field name `modified` — not `version` —
when it *is* the row's modified timestamp, so clients can key caches and
cache-busting (`?v=`) on one uniform field. Existing payloads that expose it
as `version` (map config layer entries) are grandfathered.

### D6: Standard query parameters, server-side selection reports what was served

- `lang` (compose `LanguageQuery`) and sparse fieldsets `fields[TYPE]=a,b`
  (compose the `SparseFieldsQuery` factory) are the standard narrowing
  parameters — positive selection only, allowlist-validated with 400s naming
  the valid values, `__all__` opt-in.
- Filters are named after lowercase resource attributes (`role`, `spec`,
  `show`); optional boolean filters default to *unfiltered* when omission must
  keep hidden-but-needed rows resolvable (basemap fallback chains resolve via
  inactive `show=false` layers).
- Server-side selection where the backend owns the policy: the client states
  intent (`?spec=medium`), the backend resolves (exact → nearest → single) and
  the response reports the served value (`X-Map-Spec` header /
  `metadata.wd:served_spec`), so fallback never surprises the client.

### D7: Caching tiers matched to mutability

- **Evolving documents** (catalogs, indexes — anything that must track DB
  edits): ETag + revalidate-always — `Cache-Control: public, max-age=0,
  must-revalidate, stale-if-error=604800` — one online reload is guaranteed
  fresh. Never `stale-while-revalidate` (the served-stale-then-refresh dance
  is exactly the "two reloads to see an edit" behavior), never time-based
  `cache_page` (a 6-hour window keeps serving pre-edit data).
- **Per-resource documents with per-request ETags** (hut detail/list): ETag
  computed from cheap DB aggregates (`max(modified)` + counts) + `lang` +
  query parameters + the resolved Api-Version, with a short `max-age` shared
  with the 304 path.
- **Immutable media** (SVG redirects to content-unique filenames): long
  `max-age` + `stale-while-revalidate` allowed (`REDIRECT_CACHE_CONTROL`)
  because a replaced file changes its name.
- ETag inputs must cover everything that changes the body: content version,
  `lang`, selection params, sparse fieldsets, resolved Api-Version (the
  versioning middleware may transform pinned responses).

### D8: Guidelines hook into the existing versioning runbook

The guidelines reference `docs/api-versioning.md` rather than restating it:
additive changes (which most guideline-driven new endpoints are) need no
version; making a grandfathered endpoint compliant is a breaking change and
follows the versioning runbook (fold into the unreleased version if one
exists). Route identity invariants (`name=` == `@modify(operation_id=…)`,
explicit operation ids as transform keys) are restated because every new
endpoint must satisfy them.

## Risks / Trade-offs

- [Rules written but not mechanically enforced] → contract tests + the
  committed `api_snapshot` diff act as the style linter today; a shared
  envelope helper and lint ideas are recorded as future apply-phase work in
  `tasks.md`.
- [Grandfathering creates two standards in the codebase] → accepted
  deliberately; the alternative (mass migration) is breaking everything at
  once. The doc marks grandfathered shapes explicitly so they are not copied
  as precedent.
- [Docs drift from code] → the `api-conventions` spec + the "load before
  endpoint work" agent skill anchor reviews; spec deltas force deliberate
  changes.

## Migration Plan

None — documentation-only. Future migrations happen endpoint-by-endpoint under
the versioning runbook when an endpoint is meaningfully modified anyway.

## Open Questions

- Enforcement tooling (shared envelope helper, contract-test lint for
  collection shapes): deferred to apply-phase follow-ups; scope undecided.

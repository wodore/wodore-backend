# API Design Guidelines

The Wodore house API standard for `/v1/`. It applies to every endpoint
**created or meaningfully modified** after this change — existing endpoints
are grandfathered with their current shapes until they are touched. The
condensed checklist lives in the agent skill; this page is the canonical
long-form reference.

The core principle: **predictability comes from few rules, mechanically
enforced** — not from adopting an external specification. Clients should be
able to guess the next endpoint's shape from the last one, and reviewers
should be able to check a PR against a list.

## Response shape

### Collections: envelope object

A response containing multiple resources of one type returns a top-level
object keyed by the resource name — never a bare top-level array:

```json
GET /v1/map/config
{
  "slots": [ … ],
  "layers": [ … ]
}
```

### Singletons: the bare resource

A response containing exactly one resource returns the resource object
itself, unwrapped:

- `GET /v1/huts/{slug}` → the hut DTO (`HutSchemaDetails`), not
  `{"hut": …}`
- `GET /v1/map/styles/{slug}.json` → the MapLibre style document itself

### Why the envelope over a bare array

Bare arrays are marginally simpler, but:

- **Extensibility.** An object grows new members additively — `count`,
  pagination, deprecation metadata, sibling sections like the catalog's
  `slots`. A top-level array can't take a new top-level field without
  breaking every client that expects an array.
- **Precedent.** JSON:API, the [Zalando REST API
  Guidelines](https://opensource.zalando.com/restful-api-guidelines/) and
  the [Microsoft REST API
  Guidelines](https://github.com/microsoft/api-guidelines) all mandate an
  object as the top-level collection shape. Tooling and reviewers
  pattern-match on it.
- **JSON-hijacking heritage.** The original motivation for the industry
  convention: in legacy browsers, array-topped JSON could be exfiltrated via
  `<script>` tag + `Array`/`Object` constructor overrides. The attack is
  historical; the convention it produced is durable and costs one key.

Singletons stay bare because a wrapper adds a nesting level for exactly one
element and no extensibility that the resource's own additive fields don't
already provide.

### Grandfathered shapes

`GET /v1/huts` returns a bare top-level array, and `/v1/map/catalog` mirrors
Martin's catalog shape (`{"styles": {slug: …}, "tiles": …}`). Both predate
this standard and stay as they are until meaningfully modified — do not copy
them as precedent for new endpoints. Use a shared envelope/generic helper
when one exists for the resource type; don't improvise per-endpoint shapes.

## Why not JSON:API

We cherry-picked the good ideas (sparse fieldsets, typed error codes,
content-versioned caching) but deliberately do not adopt JSON:API, OData, or
any full external API specification:

- **The API is hand-rolled on dmr.** JSON:API is a framework-shaped spec —
  its media type, `data`/`attributes` nesting, `relationships`/`included`
  graph. We would emulate it manually in every controller; the parts it
  standardizes (typed schemas, predictable field names, controlled nesting)
  are exactly what dmr + pydantic DTOs already give us.
- **Generated clients are the predictability story.** The frontend consumes
  generated OpenAPI TypeScript clients — the schema *is* the contract. A
  second meta-format on top adds ceremony without adding information.
- **Large parts of the surface are externally-spec'd formats** we must not
  wrap: GeoJSON feature collections (`/v1/huts.geojson`, availability
  endpoints), MapLibre `StyleSpecification` documents
  (`/v1/map/styles/{slug}.json`), Martin-compatible catalogs. A JSON:API
  envelope around a style document would be pure noise.
- **Migration would break everything for no gain.** Every reshape of every
  payload is a breaking API version (see [API Versioning](api-versioning.md))
  with downgrade transforms and frontend coordination — and the end state
  would be strictly less flexible than what we have.

## Errors — one contract everywhere

Every error response is the same two-field object:

```json
{
  "code": "not_found",
  "detail": "No active map layer with slug 'nope'."
}
```

- **`code`** — a machine-readable value from the shared `ErrorCode` enum
  (`server/apps/api/error_codes.py`): one code per HTTP behavioral class the
  client acts on differently (`validation_error`, `throttled`,
  `not_authenticated`, `insufficient_permission`, `not_found`, `gone`,
  `service_unavailable`).
- **`detail`** — the human-readable specific reason (which field, which
  slug, which limit).

Mechanics:

- Raise `APIError({"code": …, "detail": …}, status_code=…)` — dmr renders
  the shape uniformly.
- Use `raise_not_found(detail)` for the standard 404.
- Plain (non-dmr) views produce the same body — see `_style_error` in
  `server/apps/basemaps/api.py`.
- Never invent parallel error formats (bare strings, `{"error": …}`,
  exception dumps).

RFC 9457 problem-details alignment (additive `type`/`title`/`status`/
`instance`) is specced in the separate `error-api-problem-details` openspec
change; until it lands, the two-field contract above is the whole contract.

## Identifiers and timestamps

- **Public identifiers are slugs** — stable, human-readable, usable in
  paths (`/v1/huts/{slug}`, `/v1/map/styles/{slug}.json`). Never expose
  database PKs.
- **Content versions are `modified` timestamps** — ISO 8601 UTC, sourced
  from `TimeStampedModel.modified`. Name the field `modified`, **not**
  `version`, when it *is* the row's modified timestamp: clients key caches
  and `?v=` cache-busting on one uniform field name. (The map config's
  layer entries expose it as `version` — grandfathered; new payloads use
  `modified`.)

## Query parameters

### Standard narrowing parameters

- **`lang`** — language selection; compose `LanguageQuery`
  (`server/apps/translations/schema.py`) into the endpoint's query model.
- **Sparse fieldsets `?fields[TYPE]=name1,name2`** — compose the
  `SparseFieldsQuery` factory (`server/apps/api/query.py`):
  - positive selection only (no `exclude` — "everything except X" silently
    grows payloads when fields are added);
  - type-scoped, one nesting level per type
    (`fields[huts]=slug,sources&fields[sources]=slug,name`);
  - allowlist-validated — unknown type or field name → 400 naming the
    valid values;
  - `__all__` opts into every field.

### Filters

Filter parameters are named after lowercase resource attributes (`role`,
`spec`, `show`, `bbox`). Optional boolean filters default to **unfiltered**
when omission must keep hidden-but-needed rows resolvable — e.g. basemap
fallback chains resolve through layers with `show=false`; a default-on
filter would break them.

### Server-side selection reports what was served

Where the backend owns the policy, the client states intent and the response
reports the outcome: `?spec=medium` asks for the medium device tier, the
backend resolves exact → nearest → single variant, and the response reports
the served value (`X-Map-Spec` header, `metadata.wd:served_spec` in the
style document). Fallbacks are policy, and policy must be observable.

One spatial-filter vocabulary per endpoint family: `bbox` on collection
endpoints; `nearby` endpoints additionally return distance ordering.

## Caching and freshness

Match the caching tier to the mutability of the payload:

| Tier | Payloads | Cache-Control | Validator |
| --- | --- | --- | --- |
| Evolving documents | catalogs, indexes — anything that must track DB edits | `public, max-age=0, must-revalidate, stale-if-error=604800` | ETag over content version |
| Per-resource documents | hut detail/list | `public, max-age=60` | ETag + Last-Modified from DB aggregates |
| Immutable media | SVG redirects to content-unique filenames | `public, max-age=86400, stale-while-revalidate=604800` | — |

Rules:

- **Evolving documents use ETag + revalidate-always** — `max-age=0,
  must-revalidate` guarantees one online reload is fresh; `stale-if-error`
  keeps the app usable offline for a week after the API stops answering.
- **Never `stale-while-revalidate` for evolving documents.** SWR answers the
  first request from cache and refreshes in the background — the classic
  "needed two reloads to see my edit" behavior.
- **Never time-based `cache_page` for data that must track DB edits.** A
  6-hour window keeps serving pre-edit data. (The map catalog/config
  endpoints' `cache_page` windows are the cautionary example — grandfathered,
  don't copy.)
- **Immutable media may be long-cached.** Redirects target content-unique
  filenames: a replaced icon gets a new URL, so a briefly stale redirect is
  cheap (`REDIRECT_CACHE_CONTROL`).

ETag inputs must cover everything that changes the body:

- the content version (cheap exact aggregates: `max(modified)` + counts
  over every model the payload serializes — see
  `server/apps/huts/api/etag_utils.py`; tables without `modified` are
  content-hashed),
- `lang`,
- selection and filter parameters (`spec`, `role`, `limit`/`offset`, …),
- sparse fieldsets,
- the resolved **Api-Version** — the versioning middleware may transform
  pinned responses (`version_cache_key(request)`).

Compute the version cheaply (aggregates, optionally memoized ≤10 s) and
render bodies into a cache keyed by that version — any edit changes the key,
so the render cache is self-busting and needs no TTL.

## API versioning

Full runbook: [API Versioning](api-versioning.md). The rules that interact
with these guidelines:

- **Additive changes need no version** — new endpoints, optional
  params/fields. Most guideline-driven new work is additive.
- **Making a grandfathered endpoint compliant is breaking** (reshaping
  payloads, removing the legacy shape) — follow the runbook: fold into the
  unreleased version if one exists, otherwise create one; `VersionChange`
  downgrade transforms keyed by `operation_id`; committed snapshot; label
  `api:breaking`.
- **Every route sets `name=` on `dmr.routing.path` equal to
  `@modify(operation_id=…)`** — startup checks E003/E004 enforce it.
- **Operation ids are the downgrade-transform keys** — explicit ids are
  mandatory.

## Workflow

- **openspec first** when API-shape work changes spec'd behavior, the public
  schema, or touches 2+ modules (feature-prs Phase 2 rule).
- **Contract tests + `app api_snapshot` in the PR** — the snapshot diff is
  the style linter: an unintended envelope/field change shows up there.
- **New endpoint?** Write the OpenAPI descriptions (docstrings, `Field(...,
  description=…)`, `json_schema_extra` examples) — the generated TS clients
  are the frontend's predictability story, and they are only as good as the
  schema text.

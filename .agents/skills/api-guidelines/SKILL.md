---
name: api-guidelines
description: Wodore house API standard — the canonical long-form reference. Apply whenever creating or modifying ANY API surface in wodore-backend: controllers (dmr), request/response schemas, query parameters, envelopes and pagination, error handling, caching/ETag headers, or API versioning. Also applies to openspec changes that touch API behavior. Load BEFORE writing endpoint code or proposals.
license: MIT
---

# api-guidelines — Wodore house API standard

The `/v1/` API standard. It applies to every endpoint **created or
meaningfully modified** after the `api-conventions` capability landed
(openspec spec, archived change `2026-10-16-api-guidelines`) — existing
endpoints are grandfathered with their current shapes until they are
touched. This skill is the canonical long-form reference; condensed
checklists may mirror it, but this document wins.

The core principle: **predictability comes from few rules, mechanically
enforced** — not from adopting an external specification. Clients should be
able to guess the next endpoint's shape from the last one, and reviewers
should be able to check a PR against a list.

## Response shape

### Collections: the generic envelope

A response containing multiple resources returns the generic collection
envelope — `data` plus `count` — never a bare top-level array and never
per-resource envelope keys:

```json
GET /v1/map/layers        (reference shape for new collection endpoints)
{
  "data": [ ...resolved layers... ],
  "count": 22
}
```

- **`data`** — the array of resources.
- **`count`** — the number of items in *this* response, always present.
  (For paginating endpoints a `total` may be added — only when cheap.)

The resource type lives in the items and the type-scoped parameters
(`fields[map_layers]=…`), not in the envelope key. A client needs exactly one
collection helper / TS generic for every list endpoint in the API.

### Pagination: optional, additive, growing datasets only

Endpoints over **unbounded or growing datasets** (a paginating huts list,
activity feeds) MAY add pagination as an additive block:

- `page[size]` — page size, with a server default and a hard cap;
- `page[cursor]` — an **opaque** cursor; clients navigate by following the
  response's `next` link, never by constructing cursors;
- `total` — only when cheap to compute.

**Bounded curated registries** (map layers, slots, category trees) serve the
plain `{data, count}` envelope with **no** pagination parameters — adding
pagination to them later stays additive.

### Singletons: the bare resource

A response containing exactly one resource returns the resource object
itself, unwrapped — neither `{"hut": …}` nor `{"data": …}`:

- `GET /v1/huts/{slug}` → the hut DTO (`HutSchemaDetails`)
- `GET /v1/map/layers/{slug}` → the layer (reference example)
- `GET /v1/map/styles/{slug}.json` → the MapLibre style document itself

### Why this envelope

Bare arrays are marginally simpler, and per-resource keys read nicely in
isolation — but:

- **Uniformity.** Every collection parses identically: one client-side
  helper, one TS generic (`Collection<T>`), one review rule. Per-resource
  keys mean one helper per resource type and a per-endpoint guess.
- **Extensibility.** An object grows new members additively — pagination
  (`next`), metadata, deprecation notices — per endpoint as needed. A
  top-level array can't take a new top-level field without breaking every
  client that expects an array.
- **Lineage.** JSON:API's `data` member and Stripe's list objects are the
  two most-copied collection shapes in the industry; the [Zalando REST API
  Guidelines](https://opensource.zalando.com/restful-api-guidelines/) and
  the [Microsoft REST API
  Guidelines](https://github.com/microsoft/api-guidelines) likewise mandate
  an object as the top-level collection shape. Tooling and reviewers
  pattern-match on it.
- **JSON-hijacking heritage.** The original motivation for the
  object-at-top convention: in legacy browsers, array-topped JSON could be
  exfiltrated via `<script>` tag + `Array`/`Object` constructor overrides.
  The attack is historical; the convention it produced is durable and costs
  nothing.

Per-resource keys also duplicate information the response already carries —
the items' own shape and the type-scoped `fields[TYPE]` parameters — and they
break down the moment one response wants more than one section (the map
config's `slots` + `layers`): those are separate collections or separate
endpoints, not envelope keys.

Singletons stay bare because a wrapper adds a nesting level for exactly one
element and no extensibility that the resource's own additive fields don't
already provide.

### Grandfathered shapes

`GET /v1/huts` returns a bare top-level array, `/v1/map/catalog` mirrors
Martin's catalog shape (`{"styles": {slug: …}, "tiles": …}`), and
`/v1/map/config` uses per-resource envelope keys (`{"slots": [...],
"layers": [...]}`). All three predate this standard and stay as they are
until meaningfully modified — do not copy them as precedent for new
endpoints. Use a shared envelope/generic helper when one exists; don't
improvise per-endpoint shapes.

## Why not JSON:API

We cherry-picked the good ideas (sparse fieldsets, the generic `data`
collection member, typed error codes, content-versioned caching) but
deliberately do **not** adopt JSON:API, OData, or any full external API
specification:

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
  payload is a breaking API version (see `docs/api-versioning.md`) with
  downgrade transforms and frontend coordination — and the end state would
  be strictly less flexible than what we have.

## Errors — one contract everywhere

Every error response is a single JSON object: the Wodore members `code` and
`detail`, plus the RFC 9457 problem members `type`, `title`, `status`, and
`instance` where a resource path is identifiable:

```json
{
  "code": "not_found",
  "detail": "No active map layer with slug 'nope'.",
  "type": "https://hub.wodore.com/errors/not_found",
  "title": "The requested resource was not found.",
  "status": 404,
  "instance": "/v1/map/styles/nope.json"
}
```

- **`code`** — a machine-readable value from the `ErrorCode` enum
  (`server/apps/api/error_codes.py`): one code per HTTP behavioral class
  the client acts on differently (`validation_error`, `throttled`,
  `not_authenticated`, `insufficient_permission`, `not_found`, `gone`,
  `service_unavailable`, `api_version_sunset`). A registered RFC 9457
  extension member.
- **`detail`** — the human-readable specific reason (which field, which
  slug, which limit); may vary per occurrence.
- **`type`** — the code's stable problem-type URI
  (`{BACKEND_DOMAIN}/errors/<code>`), built from the registry. A permanent
  identifier (RFC 9457 §3.1.1): never recycled, need not be
  dereferenceable.
- **`title`** — the code's registered human summary (`PROBLEM_TITLES`);
  MUST NOT vary per occurrence.
- **`status`** — the HTTP status code mirrored as an integer.
- **`instance`** — the affected resource path; only for resource-scoped
  codes (`not_found`, `gone` — `INSTANCE_SCOPED_CODES`), omitted otherwise.

Mechanics:

- Raise `APIError({"code": …, "detail": …}, status_code=…)` — use
  `raise_not_found(detail)` for the standard 404. Plain (non-dmr) views
  raise the same errors (see `_style_error` in `server/apps/basemaps/api.py`).
- The RFC 9457 members are merged **automatically** at the single
  enrichment point (`ApiController.to_error` in
  `server/apps/api/controller.py`): every dmr controller, plain view,
  GeoJSON endpoint and the API-version middleware inherits them. Never
  hand-write the problem members.
- **New `ErrorCode` members must register their `title` and problem-type
  URI** in the same registry (a unit test fails on gaps).
- Never invent parallel error formats (bare strings, `{"error": …}`,
  exception dumps).
- The enrichment is additive across all pinned API versions — no version
  transform strips the members (openspec capability `api-errors`, change
  `error-api-problem-details`).

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

Full runbook: `docs/api-versioning.md`. The rules that interact with these
guidelines:

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

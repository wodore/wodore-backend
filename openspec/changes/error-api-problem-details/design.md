## Context

All `/v1/` errors flow through one contract: `{"code": "<ErrorCode>", "detail": "…"}` with the HTTP status carried out-of-band. Enforcement points today:

- `server/apps/api/controller.py` — `ApiController.format_error` maps dmr validation/throttle errors to `{"code", "detail"}`; `handle_error` maps `Http404`; `error_model = ErrorDetail` publishes the shape in OpenAPI; `raise_not_found` raises dmr `APIError` with the same payload.
- `server/apps/api/error_codes.py` — `ErrorCode` StrEnum: `validation_error`, `throttled`, `not_authenticated`, `insufficient_permission`, `not_found`, `gone`, `service_unavailable`.
- `server/apps/apiversions/middleware.py` — `_error_response()` writes `{"code", "detail"}` for version-resolution failures.
- Direct-write GeoJSON endpoints raise the same dmr `APIError` via `raise_not_found`/`APIError(...)`, so they share the body shape.

Clients (generated TS from the OpenAPI schema) depend on `code`/`detail`. RFC 9457 defines `type` (URI identifying the problem class; default `about:blank`), `title` (short human summary), `status` (HTTP status as int), `detail`, `instance` (URI of the affected resource) — and explicitly allows extension members such as our `code`.

## Goals / Non-Goals

- Goals: every error response carries RFC 9457 `type`/`title`/`status` (plus `instance` where identifiable) derived from the ErrorCode registry; `code`/`detail` byte-identical to today; one shared implementation inherited by all surfaces; OpenAPI documents the shape.
- Non-Goals:
  - **Media type change** to `application/problem+json` — client-visible (content negotiation, generated clients) and buys nothing functionally; our bodies are `application/json` with problem members. Possible later *opt-in* via content negotiation, recorded here so it is a decision, not an omission.
  - Removing, renaming or re-mapping any existing `code` value; changing any `detail` text or status code.
  - RFC 9457 `errors` array / parameter-level validation detail (`detail` stays the joined message; field-level structure is a separate future proposal if ever needed).
  - Frontend consumption of the new members (separate repo, opportunistic follow-up).

## Decisions

### D1: Additive only — `code` + `detail` stay verbatim

Every existing member, value and status is preserved; `type`, `title`, `status`, `instance` are *added*. RFC 9457 §3.1 explicitly permits extension members, so `code` is a first-class problem-details extension, not a legacy wart. Rationale: generated clients and any pinned client keep working unchanged — zero migration cost, zero version machinery. Alternative considered: rename `detail` (it is already RFC 9457's member name) or map `code`→`type` and drop it — rejected, that is a breaking rename with no upside; `code` (snake_case, Wodore-specific behavior classes) and `type` (URI, problem class) serve different layers.

### D2: Media type stays `application/json`

Switching to `application/problem+json` changes a client-visible response header — every cache, proxy and generated client that validates content type observes it. That fails the versioning litmus test for zero functional gain (the fields are equally readable in either media type). Recorded follow-up: an opt-in `Accept: application/problem+json` negotiation could serve the enriched body under the registered media type later; that would be additive and is the *only* sanctioned path (a default flip stays out of scope).

### D3: `type`/`title` derive from the ErrorCode registry — one mapping, not per-raise-site

The `ErrorCode` enum is the existing single behavioral discriminator (one code per client behavior). The registry gains, per code: a human `title` (e.g. `not_found` → "The requested resource was not found") and a stable `type` URI. `type` uses the URL form `https://hub.wodore.com/errors/<snake_case_code>` (e.g. `.../errors/not_found`) — resolvable-looking and self-documenting; the host is the public API origin (setting-driven, not hardcoded per call site). `status` mirrors the HTTP status of the response (int, per RFC). `instance` is set only where a resource path is identifiable (e.g. 404/410 on a hut detail path carries the request path); it is omitted otherwise — RFC 9457 makes it optional and most of our errors (validation, throttle, auth) have no affected-resource URI worth asserting. Alternative considered: `about:blank` + no registry mapping — rejected; the registry is exactly the "problem type" concept and we are 80% there.

### D4: One shared implementation — error surfaces inherit, nobody opts in

Enrichment lives in the shared error machinery, not in handlers: `ApiController.format_error` + `handle_error` (covers all dmr controllers, since validation/throttle/404 mapping funnels there), a small helper used by `raise_not_found`/direct `APIError` construction so the payload is enriched at the response-writing boundary (dmr `to_error`), and `ApiVersionMiddleware._error_response`. GeoJSON plain views and every dmr controller therefore produce the enriched body with no per-endpoint work; a lint/test guarantee (contract tests hit representative surfaces) prevents drift. Alternative considered: a response middleware that patches error bodies — rejected: it would re-encode every error response (the versioning middleware already does decode/re-encode for downgrades; a second pass adds fragility around streaming/binary error paths) and would duplicate knowledge the exception handlers already have.

**ApiVersionMiddleware interplay**: error enrichment applies to **all versions, including pinned ones**. Litmus reasoning: the versioning policy asks "would a client pinned to the current version behave differently?" — additional JSON members are ignorable by any spec-compliant JSON client (unknown members must be tolerated), so behavior is unchanged, same reasoning as any additive response field. This mirrors how the middleware already treats error bodies: it only *downgrades* (removes/reshapes) for pinned clients when a `VersionChange` transform says so — no transform is registered here, so enriched bodies pass through untouched. The middleware's own version-resolution errors (`validation_error` for header/query mismatch or unknown version) are enriched too, for consistency; they are emitted before a controller exists, which is exactly why `_error_response` gets the shared helper.

### D5: No new API version; unreleased version notes the fields

Additive error-body fields need no `VersionChange` (repo rule: versions are only for breaking changes). The registry currently holds an `UNRELEASED` placeholder version; the enriched error fields appear there (and in every version) with no transform — when that version releases, its description mentions that error bodies gained RFC 9457 members. Snapshot regeneration (`app api_snapshot`) is still required because the OpenAPI `error_model` schema changes (additive optional members).

## Risks / Trade-offs

- [Body size] Four extra members on every error → negligible; errors are small and cache-unfriendly by design.
- [Registry drift] A code raised without a registered title/type would silently lose enrichment → the helper keys off the `ErrorCode` enum itself (mapping lives beside the enum); a unit test asserts every enum member has title + type URI.
- [Double-field confusion] `status` member vs HTTP status line could drift if handlers pass different values → the helper takes the response status as its single source; contract tests assert equality.
- [ETag interplay] Error responses from hut endpoints: ETags key on the resolved version + registry hash; enrichment is body-additive and version-independent (D4/D5), so no ETag input changes — verified in the apply phase.
- [Type URI host stability] `https://hub.wodore.com/errors/...` URLs are identifiers, not dereferenceable requirements (RFC 9457 §3.1.1); if the host ever moves, the URN stays stable per registry and only the *default* template changes → document that URIs are permanent identifiers in the registry docstring.

## Migration Plan

Apply phase ships the machinery + tests in one PR; rollout is a normal deploy (no data, no feature flag, no coordinated client change). Rollback = revert; no persisted state. Snapshot regen in the same PR per API rules.

## Open Questions

- Should `instance` carry the full request path or only the resource-identified prefix? (Apply-phase decision; default: full request path — cheap and unambiguous.)
- Should the future `application/problem+json` opt-in be specced now? Deferred — recorded as a non-goal until a client asks for it.

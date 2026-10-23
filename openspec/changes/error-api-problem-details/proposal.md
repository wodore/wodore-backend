## Why

Every Wodore API error already answers in one predictable contract — `{"code": "<ErrorCode>", "detail": "…"}` — established once in `ApiController` and reused by every dmr controller, `raise_not_found`, the GeoJSON views and the ApiVersion middleware. That is ~80% of RFC 9457 (Problem Details for HTTP APIs): we have a machine-readable discriminator, a human message, and an HTTP status. What is missing is the documented, industry-standard interop story: generic HTTP clients, gateways and logging tooling that understand `type`/`title`/`status`/`instance` cannot use our shape today because those members are absent and undocumented. Adopting RFC 9457 additively closes that gap without touching a single existing client (generated TS clients depend on `code`/`detail`, which stay verbatim).

## What Changes

- Error bodies gain the optional RFC 9457 members `type`, `title`, `status` (and `instance` where a resource path is identifiable), populated from the existing `ErrorCode` registry — one shared implementation in the error machinery (`ApiController.format_error`/`handle_error`, `raise_not_found`, dmr `APIError` responses, `ApiVersionMiddleware` error responses), so every dmr controller, plain view and GeoJSON endpoint inherits automatically; no per-endpoint work.
- `code` and `detail` are preserved verbatim — no removals, renames or value changes. `code` remains a registered RFC 9457 *extension member* (explicitly allowed by the spec).
- The `ErrorCode` registry becomes the single source of truth for each code's stable problem `type` URI and human `title`.
- The OpenAPI error schema (dmr `error_model`) documents the enriched shape.
- Media type stays `application/json` (switching to `application/problem+json` is a client-visible change — explicitly out of scope; see design non-goals).
- No new API version: purely additive response fields (litmus test: a client pinned to the current version behaves identically).

## Capabilities

### New Capabilities

- `api-errors`: the single API error contract — preserved `code`/`detail`, RFC 9457 additive members derived from the ErrorCode registry, shared-machinery inheritance across all serving surfaces, and versioning behavior for pinned clients.

### Modified Capabilities

(none — `openspec/specs/api-throttling`'s "Throttled responses follow the standard error contract" requirement pins the `{"code", "detail"}` minimum shape, which remains satisfied; additive fields do not change that requirement's behavior)

## Impact

- **Backend**: `server/apps/api/error_codes.py` (per-code title + type URI), `server/apps/api/controller.py` (`ApiController.format_error`/`handle_error`, `raise_not_found`, `error_model`), `server/apps/apiversions/middleware.py` (`_error_response`) — all in the apply phase; this change is the proposal only.
- **API**: additive error-body fields on every `/v1/` error response; no `VersionChange`, but snapshot regeneration and contract tests required per repo API rules (error bodies appear in the OpenAPI schema via `error_model`).
- **Clients**: none required — generated TS clients keep working; new members are ignorable unknown JSON fields. Frontend may later surface `title`/`instance` opportunistically (follow-up, separate repo).
- **Docs**: API versioning runbook and error-code docs gain a "problem details" section.

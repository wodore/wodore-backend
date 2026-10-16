## 1. ErrorCode registry enrichment

- [ ] 1.1 Extend `server/apps/api/error_codes.py`: per-code human `title` and stable problem `type` URI (`https://hub.wodore.com/errors/<snake_case_code>`, host from API-origin settings) for all seven codes, documented as permanent identifiers
- [ ] 1.2 Add a registry helper (e.g. `problem_fields(code, status, instance=None)`) returning the RFC 9457 members for a code + status, with `instance` omitted when not identifiable
- [ ] 1.3 Unit test: every `ErrorCode` member has a title + type URI; helper output matches the spec'd shapes (status mirrors the HTTP status)

## 2. Shared machinery

- [ ] 2.1 `ApiController.format_error` + `handle_error` (`server/apps/api/controller.py`): merge the problem members into every produced error body (validation, throttle, Http404 paths)
- [ ] 2.2 Enrich the dmr `APIError` response-writing boundary used by `raise_not_found` and direct `APIError(...)` raises (GeoJSON/plain views inherit without per-endpoint work); decide and document the `instance` rule from design.md (default: full request path where a resource is identifiable)
- [ ] 2.3 `ApiVersionMiddleware._error_response` (`server/apps/apiversions/middleware.py`): emit enriched bodies for header/query mismatch and unknown-version errors (`instance` omitted)
- [ ] 2.4 Verify no version transform registers and no `VersionChange` is needed (additive; `python3 -m server.apps.apiversions.registry_check` passes) — note the fields in the existing `UNRELEASED` version description per design D5

## 3. OpenAPI + snapshot

- [ ] 3.1 Update `error_model` (`ErrorDetail` TypedDict) to document optional `type`, `title`, `status`, `instance` alongside `code`/`detail`
- [ ] 3.2 Regenerate the API snapshot (`app api_snapshot`) and commit it in the apply PR

## 4. Contract tests

- [ ] 4.1 404 shape: `code`/`detail` preserved + `type`/`title`/`status`/`instance` present (hut detail path)
- [ ] 4.2 Validation error shape: 400 body with problem members, `instance` omitted
- [ ] 4.3 Throttled shape: 429 with `code` `"throttled"`, problem members, `Retry-After`/`X-RateLimit-*` headers unchanged
- [ ] 4.4 GeoJSON endpoint + middleware version-error surfaces produce the same enriched shape (shared-machinery inheritance)
- [ ] 4.5 Pinned-version client: error response with `Api-Version` pin carries additive fields, nothing stripped; `status` member equals HTTP status
- [ ] 4.6 ETag interplay check: hut-endpoint error ETag inputs unchanged (design risk item)

## 5. Verification

- [ ] 5.1 Lane test suite green (`scripts/lane-run.sh .venv/bin/pytest`)
- [ ] 5.2 Update docs: error-code docstrings/module docstring + API versioning runbook mention RFC 9457 members and the `application/problem+json` non-goal

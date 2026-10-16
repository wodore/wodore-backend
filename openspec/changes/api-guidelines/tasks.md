## 1. Docs page (this change — documentation only)

- [x] 1.1 Write `docs/api-guidelines.md`: the canonical long-form house API
  standard — response shape (collection envelope / bare singleton +
  rationale), why-not-JSON:API, single error contract, slugs + ISO
  `modified`, standard query parameters, caching tiers, versioning
  integration, workflow
- [x] 1.2 Add the mkdocs nav entry ("API Guidelines", after "API") in
  `mkdocs.yml`
- [x] 1.3 `openspec validate api-guidelines` green; docs build green

## 2. Future — apply-phase follow-ups (NOT this change)

**No existing endpoint is migrated.** Everything below is deliberately
deferred and tracked here so it is not lost; none of it ships in this
documentation-only change:

- Shared collection-envelope helper (generic `{"<resource>": [...]}` response
  model builder) — introduced when the next collection endpoint is built;
  grandfathered endpoints adopt it only when meaningfully modified (each
  adoption is a breaking change → versioning runbook).
- Contract-test linting ideas (mechanically enforce the envelope rule and the
  error contract on the OpenAPI snapshot: fail if a new 2xx response schema
  is a bare top-level array or an error schema deviates from
  `{code, detail}`).
- RFC 9457 problem-details alignment — owned by the separate
  `error-api-problem-details` openspec change.
- Candidate grandfathered cleanups, each behind its own versioned change
  when the endpoint is touched anyway: `/v1/map/catalog` ↔ `/v1/map/config`
  duplication, map endpoints' time-based `cache_page` windows (replace with
  ETag + revalidate-always), `version` → `modified` field rename in map
  config layer entries.

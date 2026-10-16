## 1. Agent skill (this change — documentation only)

- [x] 1.1 Create `.agents/skills/api-guidelines/SKILL.md`: the canonical
  long-form house API standard — response shape (generic `{data, count}`
  collection envelope +
  optional `page[size]`/`page[cursor]` pagination for growing datasets /
  bare singleton + rationale), why-not-JSON:API, single error contract
  (RFC 9457-aligned: `code`/`detail` + `type`/`title`/`status`/`instance` via
  the shared `to_error` machinery, per the landed `error-api-problem-details`
  change), slugs
  + ISO `modified`, standard query parameters, caching tiers, versioning
  integration, workflow
- [x] 1.2 Deliver as a repo-tracked agent skill instead of a mkdocs page
  (dmr-skill convention in `.agents/skills/`); no `docs/` page, no nav entry
- [x] 1.3 `openspec validate api-guidelines` green

## 2. Future — apply-phase follow-ups (NOT this change)

**No existing endpoint is migrated.** Everything below is deliberately
deferred and tracked here so it is not lost; none of it ships in this
documentation-only change:

- Shared generic collection-envelope helper (a `{"data": [...], "count": N}`
  response-model builder, optionally paired with the `page[size]`/
  `page[cursor]` pagination block) — introduced when the next collection
  endpoint is built; grandfathered endpoints adopt it only when meaningfully
  modified (each adoption is a breaking change → versioning runbook).
- Contract-test linting ideas (mechanically enforce the envelope rule and the
  error contract on the OpenAPI snapshot: fail if a new 2xx response schema
  is a bare top-level array or an error schema deviates from the
  RFC 9457-enriched `{code, detail}` contract).
- RFC 9457 problem-details alignment — **landed on main** (`error-api-problem-details`,
  #329); the skill's error section documents the landed contract.
- Candidate grandfathered cleanups, each behind its own versioned change
  when the endpoint is touched anyway: `/v1/map/catalog` ↔ `/v1/map/config`
  duplication, map endpoints' time-based `cache_page` windows (replace with
  ETag + revalidate-always), `version` → `modified` field rename in map
  config layer entries.

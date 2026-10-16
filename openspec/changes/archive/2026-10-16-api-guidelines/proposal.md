## Why

The API's conventions exist in practice — the `{code, detail}` error contract, ETag
revalidation, sparse fieldsets, slug identifiers — but they live only in code review
comments and reviewer heads, so they drift: `/v1/map/catalog` and `/v1/map/config`
grew into two overlapping catalog endpoints with different shapes, the map endpoints
serve through a 6-hour `cache_page` window that keeps serving stale data after DB
edits, and payload fields ad-hoc (`version` vs `modified` for the same timestamp).
There is no single reference a reviewer, a new lane, or the frontend team can check
an endpoint against.

## What Changes

- New repo-tracked agent skill `.agents/skills/api-guidelines/SKILL.md` (the
  canonical long-form reference, dmr-skill convention): the Wodore house API
  standard — response shape (generic
  `{data, count}` collection envelope with optional pagination for growing
  datasets / bare singleton), the single error contract (RFC 9457-aligned:
  `code`/`detail` + problem members via the shared machinery), slug
  identifiers + ISO `modified`
  timestamps, standard query parameters (`lang`, `fields[TYPE]`, server-side
  selection with served-value reporting), caching tiers (revalidate-always + ETag,
  immutable media, prohibitions), and API-versioning integration.
- New capability spec `api-conventions` capturing the same rules as requirements
  with scenarios, so future openspec changes can extend or modify them deliberately
  instead of silently diverging.
- **No code changes, no endpoint migrations.** Existing endpoints are grandfathered
  until meaningfully touched; moving them onto the standard is a breaking API change
  per `docs/api-versioning.md` and is explicitly out of scope.

## Capabilities

### New Capabilities

- `api-conventions`: the house API design standard — generic collection envelope
  + optional pagination / bare singleton response shape, single error contract
  (RFC 9457-aligned),
  identifiers and timestamps, standard query
  parameters, caching tiers, and versioning integration for every endpoint created
  or meaningfully modified after this change.

### Modified Capabilities

(none — no existing spec's requirements change; existing endpoints keep their
current, grandfathered contracts)

## Impact

- **Docs/skills**: `.agents/skills/api-guidelines/SKILL.md` (new repo-tracked
  agent skill). The skill becomes the canonical long-form reference —
  auto-loaded by API-shape work; condensed checklists point at it. The error
  section reflects the landed RFC 9457 enrichment (`error-api-problem-details`,
  main #329).
- **Code**: none in this change. Future enforcement helpers (shared envelope
  helper, contract-test linting) are recorded as apply-phase follow-ups in
  `tasks.md`.
- **API surface**: unchanged — no `VersionChange`, no snapshot regeneration
  (docs-only: label `type:docs` per `docs/api-versioning.md`).

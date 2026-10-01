## API Versioning

The API (`/v1/`) uses Stripe-style date-based contract versioning. One codebase
runs the newest logic; clients pin a version via the `Api-Version` request header
(or `api_version` query parameter) and keep receiving the response shape they
were built against until that version is sunset.

- Registry: `server/apps/apiversions/registry.py` (versions, transforms, endpoint deprecations)
- Design: `openspec/changes/add-api-date-versioning/design.md`
- Changelog: `CHANGELOG_API.md` (generated with `cliff-api.toml`)
- Discovery: `GET /v1/version` returns the `api` block (current/default/supported versions)
- Docs: `/v1/docs` has a version switcher; `/v1/openapi.json?api_version=<v>` serves the frozen snapshot

**Rules**

- Additive changes (new endpoints, optional fields/params) need no new version.
- A new version is created **only** for breaking changes, via a `VersionChange` entry.
- Minimum deprecation period: 6 months before a version's sunset.
- Transforms are keyed by `operation_id` — endpoints with transforms must have an
  explicit `operation_id` (a system check fails startup otherwise).

### What counts as breaking?

Litmus test: **would a client pinned to the current version behave differently
after this deploy?** Yes → breaking (new version). No — it simply never
encounters the new functionality → additive (label `api:added`, live in all
versions).

| Change | Classification |
|---|---|
| New endpoint | additive |
| New optional query/body param (default preserves current behavior) | additive |
| New optional response field | additive* |
| Loosening validation (accepting more values) | additive |
| Removing/renaming fields, params or endpoints | **breaking** |
| New *required* request param | **breaking** (old requests start 400ing) |
| Tightening validation on an existing param (e.g. lowering `limit` max) | **breaking** |
| Changing a field's type or format | **breaking** |
| Changing observable defaults (sort order, pagination semantics) | **breaking** |
| Changing error codes/shape for existing conditions | **breaking** |
| New enum value in an existing *response* field | **breaking** (clients switch on enums) |

\* Assumes tolerant readers (JSON clients that ignore unknown fields — our
mobile/web apps are). If a strict-schema third party ever depends on the API,
revisit this row.

You are never "too late to pin": the `VersionChange` and its downgrade
transforms are written in the **same PR** as the breaking change — older
shapes are reconstructed from the new code at the edge, not frozen.

### Docs-only changes (help text, descriptions)

Descriptions in the live schema (`/v1/openapi.json`, `/v1/docs`) are generated
from the code at request time — improvements are visible immediately. Label
`type:docs`; **no new version, no snapshot regeneration, no `api:*` label**.

Committed snapshots are frozen at release: they document the contract as
shipped with that version and intentionally lag behind docs improvements; the
next version's snapshot picks them up. CI checks snapshot *presence*, not
content, so this drift is expected. (Regenerating the current snapshot on docs
PRs is allowed but not recommended — it churns the frozen baseline the
`oasdiff` guard diffs against.)

### Introducing a breaking change

1. Add a `VersionChange` to `server/apps/apiversions/registry.py` (date,
   description, `responses` downgrades keyed by operation id; `requests` upgrades
   if request shape changed). Mark the **previous** version
   `deprecation_date`/`sunset_date` (≥ 6 months out).
2. Write downgrades defensively (`pop(key, None)`, tolerate missing/null fields).
   For GeoJSON use the `feature_properties()` helper; for lists `each()`.
   Direct-write endpoints (`huts.geojson`, `availability/{date}.geojson`) already
   call `apply_response_transforms()` — just register the transform.
3. Add contract tests validating the old version's responses against its snapshot.
4. Label the PR `api:breaking` (CI fails if the registry has no matching change).
5. Continue below with *Releasing an API version*.

### Releasing an API version

The **snapshot is committed in the breaking PR itself** (CI fails otherwise,
since the registry entry and snapshot must land together):

```bash
app api_snapshot          # freeze the schema for the current registry version
git add server/apps/apiversions/openapi/<version>.json
```

The **release artifacts** (tag + API changelog) are cut automatically by
`inv release`: every API release is also a backend release (deploys need
the docker build), so whenever the registry carries an untagged version,
`inv release` tags `api/<version>`, pushes the tag and regenerates
`CHANGELOG_API.md` alongside the backend changelog — commit both together.
`inv api-release` (standalone) remains available for cutting it manually,
e.g. right after a PR merges.

CI runs `app api_snapshot --check` — the build fails if the current registry
version has no committed snapshot. Snapshots of released versions are frozen:
`app api_snapshot` refuses to regenerate them once `api/<version>` is tagged
(`--force` overrides — you should not need it).

### Sunsetting a version

The sunset date lives in the registry (`sunset_date` of the version's
`VersionChange`). No code action needed at the date: versions past their sunset
automatically answer `410 api_version_sunset`. Announce via the
`Deprecation`/`Sunset` headers (sent automatically once `deprecation_date` is
set) and the `api:deprecated` PR label. After the sunset has been live for a
while, the `VersionChange` entry and its transforms stay in the registry (the
version is simply rejected) — remove them only together with the snapshot file.

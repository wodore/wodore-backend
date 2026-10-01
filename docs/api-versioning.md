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

1. **Check the current version's release state first** — `python3 -m
   server.apps.apiversions.registry_check` (or look for the `api/<version>`
   tag). If the current version is **still unreleased** (no tag yet — the
   docker build hasn't shipped it), **amend it** instead of adding a new
   version: merge/extend its `VersionChange` transforms, keep its version
   date, regenerate its snapshot. A version no client ever received must
   not become its own contract boundary, and CI would never tag it. CI
   (test.yml `api-registry` step) rejects stacking a new version on an
   unreleased one.
2. Add a `VersionChange` to `server/apps/apiversions/registry.py` (date,
   description, `responses` downgrades keyed by operation id; `requests` upgrades
   if request shape changed). Mark the **previous** version
   `deprecation_date`/`sunset_date` (≥ 6 months out).
3. Write downgrades defensively (`pop(key, None)`, tolerate missing/null fields).
   For GeoJSON use the `feature_properties()` helper; for lists `each()`.
   Direct-write endpoints (`huts.geojson`, `availability/{date}.geojson`) already
   call `apply_response_transforms()` — just register the transform.
4. Add contract tests validating the old version's responses against its snapshot.
5. Label the PR `api:breaking` (plus its `type:*` label) — CI fails if the
   registry has no matching change, and the `api-registry` step validates
   the release-state invariant.
5. Continue below with *Releasing an API version*.

### Releasing an API version

The **snapshot is committed in the breaking PR itself** (CI fails otherwise,
since the registry entry and snapshot must land together):

```bash
app api_snapshot          # freeze the schema for the current registry version
git add server/apps/apiversions/openapi/<version>.json
```

The **`api/<version>` tag is cut by CI** (`.github/workflows/new-api-version.yml`,
mirroring the `new-version.yml` pattern): when the docker build that ships
the registry's current version succeeds, the tag is created and pushed —
every API release is an app release, so the tag anchors at the build that
deploys it. **`CHANGELOG_API.md` is regenerated by `inv release`** (it also
runs the API steps automatically; `inv api-release` remains available as a
manual fallback that can cut a missed tag).

CI runs `app api_snapshot --check` — the build fails if the current registry
version has no committed snapshot. Snapshots of released versions are frozen:
`app api_snapshot` refuses to regenerate them once `api/<version>` is tagged
(`--force` overrides — you should not need it).

### Changelogs and labels

API changes appear in **both** changelogs:

- `CHANGELOG.md` (backend): via the normal `type:*` labels — label API PRs
  with a `type:*` label **and** the `api:*` label (e.g. `type:feature` +
  `api:breaking`). PRs labeled only `api:*` still appear here as a safety
  net (`api:breaking` → Breaking changes, `api:added` → Features,
  `api:deprecated` → Deprecations, `api:fixed` → Fixes).
- `CHANGELOG_API.md` (API): only `api:*`-labeled PRs, grouped per
  `api/<version>` tag; non-breaking entries under "Live in all versions".

### Sunsetting a version

The sunset date lives in the registry (`sunset_date` of the version's
`VersionChange`). No code action needed at the date: versions past their sunset
automatically answer `410 api_version_sunset`. Announce via the
`Deprecation`/`Sunset` headers (sent automatically once `deprecation_date` is
set) and the `api:deprecated` PR label. After the sunset has been live for a
while, the `VersionChange` entry and its transforms stay in the registry (the
version is simply rejected) — remove them only together with the snapshot file.

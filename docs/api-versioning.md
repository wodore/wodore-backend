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

```bash
app api_snapshot          # freeze the schema for the current registry version
git add server/apps/apiversions/openapi/<version>.json
git commit -m "Snapshot API version <version>"
git tag api/<version> && git push origin api/<version>
git-cliff --config cliff-api.toml -o CHANGELOG_API.md   # needs GITHUB_TOKEN
git commit CHANGELOG_API.md -m "Update API changelog"
```

CI runs `app api_snapshot --check` — the build fails if the current registry
version has no committed snapshot.

### Sunsetting a version

The sunset date lives in the registry (`sunset_date` of the version's
`VersionChange`). No code action needed at the date: versions past their sunset
automatically answer `410 api_version_sunset`. Announce via the
`Deprecation`/`Sunset` headers (sent automatically once `deprecation_date` is
set) and the `api:deprecated` PR label. After the sunset has been live for a
while, the `VersionChange` entry and its transforms stay in the registry (the
version is simply rejected) — remove them only together with the snapshot file.

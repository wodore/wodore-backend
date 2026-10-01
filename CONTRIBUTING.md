# Contributing

Thanks for contributing to wodore-backend! This covers the essentials; the
[docs](https://wodore.github.io/wodore-backend/) have the details.

## Pull requests

- PR titles are changangelog-ready: imperative, capitalized, no
  conventional-commit tags (`feat:` / `fix:`) — the title lands in
  `CHANGELOG.md` verbatim (generated with git-cliff from PR labels).
- Label every PR with a **type label** (`type:feature`, `type:bug`,
  `type:refactor`, `type:docs`, `type:deps`, `type:others`, `type:tooling`;
  `BREAKING` or `INTERNAL` where applicable) — unlabeled PRs are skipped
  from the changelog.
- Changes touching the HTTP API additionally get an **`api:*` label**
  (`api:breaking`, `api:added`, `api:deprecated`, `api:fixed`) — they then
  also appear in `CHANGELOG_API.md` (the per-version API changelog).

## API changes and versioning

The API (`/v1/`) uses date-based contract versioning: clients pin a version
via the `Api-Version` header (or `api_version` query parameter). Full
reference: [`docs/api-versioning.md`](docs/api-versioning.md) — the short
version:

| Change | Action |
|---|---|
| New endpoint, optional param/field, docs text | Nothing — additive, label `api:added` (or `type:docs`) |
| **Breaking** (remove/rename, new required param, tightened validation, changed defaults, new response enum value) | New `VersionChange` in `server/apps/apiversions/registry.py` + downgrade transforms + snapshot (`app api_snapshot`, committed in the PR) + contract tests. Label `type:*` **and** `api:breaking` |
| Breaking change while the current version is still unreleased | **Amend** that version's `VersionChange` (merge transforms, same date, regenerate snapshot) — CI rejects stacking a new version on an unreleased one |

Check the release state any time:

```bash
python3 -m server.apps.apiversions.registry_check
```

## Releasing

```bash
inv release
```

Prepares the backend release (`CHANGELOG.md`, version bump) and regenerates
`CHANGELOG_API.md` when needed. CI cuts the tags: `v*` and — when the docker
build shipping a new API version succeeds — `api/<date>`
(`new-api-version.yml`, mirroring `new-version.yml`). Snapshots of released
versions are frozen; CI fails if the current registry version has no
committed snapshot.

## Testing

Run the test suite before considering work done (`inv tests`, or
`scripts/lane-run.sh .venv/bin/pytest` in a worktree). New API behavior
needs tests under `tests/apps/` — see `tests/apps/apiversions/` for the
versioning suite.

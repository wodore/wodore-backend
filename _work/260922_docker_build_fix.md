# Docker build fixes (all distros)

CI run: https://github.com/wodore/wodore-backend/actions/runs/35663674160 (Build Docker #140, main, workflow_dispatch)

## Root cause

All three Dockerfiles drifted, breaking `docker build`:

1. **Alpine (the CI failure)**: `Dockerfile.alpine` used the floating base image
   `ghcr.io/osgeo/gdal:alpine-small-latest` together with `PYTHON_VERSION=3.12`
   (`apk add python3=~3.12`). `latest` has been rebased onto Alpine 3.24, whose
   repos ship python 3.14 only → apk fails with
   `python3-3.14.7-r1: breaks: world[python3~3.12]`.
2. **Ubuntu (same class, verified locally)**: `ubuntu-small-latest` is now
   Ubuntu 26.04 with python 3.14 → `UV_PYTHON=python3.12` with
   `UV_PYTHON_DOWNLOADS=never` cannot be satisfied.
3. **Debian (stale)**: still on poetry while `poetry.lock` no longer exists
   (project moved to uv), had a shell syntax error in the builder `RUN`
   (`wget` line without `\` continuation before `&& dpkgArch=…`), and
   `COPY ./static` references a directory that no longer exists (and is
   dockerignored).

## Tag research (2026-09-22)

| gdal tag | base | python3 |
|---|---|---|
| `alpine-small-latest` | Alpine 3.24 | 3.14.7 ✗ |
| `alpine-small-3.13.3` | Alpine 3.23.5 | 3.12.14 ✓ |
| `ubuntu-small-latest` | Ubuntu 26.04 | 3.14.4 ✗ |
| `ubuntu-small-3.13.x` | Ubuntu 26.04 | 3.14.4 ✗ |
| `ubuntu-small-3.12.4` | Ubuntu 24.04.4 | 3.12.3 ✓ |

## Changes

- `docker/django/Dockerfile.alpine`
  - base pinned to `ghcr.io/osgeo/gdal:alpine-small-3.13.3` (Alpine 3.23, python 3.12)
  - uv pinned `0.7.2` → `0.11.16` (matches the version that wrote `uv.lock`;
    kept in sync across all Dockerfiles)
- `docker/django/Dockerfile.ubuntu`
  - base pinned to `ghcr.io/osgeo/gdal:ubuntu-small-3.12.4` (Ubuntu 24.04, python 3.12)
  - uv pinned `latest` → `0.11.16`
- `docker/django/Dockerfile.debian`
  - converted poetry → uv (mirrors the ubuntu builder; poetry.lock is gone)
  - builder `RUN` rewritten as heredoc, fixing the pre-existing syntax error
  - removed ssh-keyscan setup (deps come via https + token insteadOf now)
  - removed `COPY ./static`, added `collectstatic` at build time (like alpine)
  - normalized `FROM … AS` casing

## Verification

Full builds (production target, `WITH_DEV=0`, no secrets → public packages only)
succeed for all three:

| image | python | GDAL | build | `manage.py check` |
|---|---|---|---|---|
| `wodore-backend:fix-alpine` | 3.12.14 | 3.13.3 | ✓ | no issues |
| `wodore-backend:fix-ubuntu` | 3.12.3 | 3.12.4 | ✓ | no issues |
| `wodore-backend:fix-debian` | 3.12.13 | 3.6.2 | ✓ | no issues |

The `uv sync --locked` step resolved 280 packages from the existing lock in all
three images. CI builds run with `READ_GITHUB_TOKEN`/`READ_GITHUB_USER` secrets
and additionally install the `private` extra — that path is unchanged from the
working alpine/ubuntu flow.

Python code is untouched, so the regular test suite is unaffected; verification
here was the three image builds plus `manage.py check` smoke tests.

## Follow-ups (not done here)

- Consider a scheduled CI job building all three distros to catch base-image
  drift early (the `Build`-label gate on push means broken builds can go
  unnoticed, as happened between April and September).
- When bumping `PYTHON_VERSION` (e.g. to 3.13/3.14), the pinned gdal tags must
  be re-evaluated — comments at the top of each Dockerfile explain this.
- uv version is now pinned in three places; could be moved to a single
  `ARG UV_VERSION` per file when touched next.

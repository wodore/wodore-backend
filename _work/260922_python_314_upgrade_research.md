# Python upgrade research: 3.12 → 3.13/3.14 (what is needed)

Date: 2026-09-22 · Branch: `research/python-upgrade` (off `main` @ 9a7edb5)

## Version landscape (Sep 2026)

| Version | Status | Patch | EOL |
|---|---|---|---|
| 3.12 (current) | maintenance | 3.12.14 | 2028-10 |
| **3.13** (2nd latest) | security-only?/maintenance | 3.13.7 | 2029-10 |
| **3.14 (latest)** | maintenance | 3.14.5 (uv) / 3.14.7 (apk) | 2030-10 |
| 3.15 | due 2026-10 | rc | — |

**Recommendation: target 3.14**, not 3.13. Reason: no gdal base image ships
python 3.13 at all (Alpine 3.23 = 3.12 → 3.24 = 3.14; Ubuntu 24.04 = 3.12 →
26.04 = 3.14 — both skip 3.13), so 3.13 would force the debian-style
build-your-own-python approach in every image. 3.14 is a year old, supported by
Django 6 and all our deps.

## Verified compatibility (this worktree)

- `uv sync --locked` (no relock needed — lock already has 3.14 resolution
  markers) installs **prod + dev deps on 3.13.7 and 3.14.5**, all as wheels
- Import smoke test on 3.14.5: Django 6.0.3 loads **all 58 apps**;
  psycopg2-binary 2.9.11 (cp314 wheel), pydantic 2.12.5, pyosmium 4.3.0,
  opening-hours-py 1.2.0, django-ninja 1.6, structlog — all OK
  (PEP 649 deferred annotations are handled by Django 6 / pydantic 2.12)
- Code grep for stdlib removed in 3.13/3.14 (cgi, telnetlib, pipes, imghdr,
  distutils, …): **no usage**. Only `datetime.utcnow()` in
  `server/apps/huts/management/commands/martin_sync.py:723,733` (deprecated
  since 3.12, still works — should be switched to
  `datetime.now(timezone.utc)` in the upgrade PR)
- hut-services / hut-services-private: `requires-python >=3.10` — no constraint

## What needs to change (3.14)

| Where | Today | Change |
|---|---|---|
| `.python-version` | `3.12` | `3.14` — single source of truth for CI (setup-uv-env uses `python-version-file`) and local dev |
| `Dockerfile.ubuntu` | `ubuntu-small-3.12.4`, `PYTHON_VERSION=3.12` | `ubuntu-small-3.13.3` (Ubuntu 26.04, py **3.14.4**, GDAL 3.13.3 stable) + `PYTHON_VERSION=3.14` |
| `Dockerfile.debian` | `python:3.12.13-slim-bookworm`, `UV_PYTHON=python3.12` | `python:3.14.5-slim-bookworm` (or trixie) + `UV_PYTHON=python3.14` |
| `Dockerfile.alpine` | `alpine-small-3.13.3` (py 3.12), `PYTHON_VERSION=3.12` | ⚠ no pinned gdal tag with py 3.14 exists yet — see decision below |
| `.github/actions/setup-venv/action.yml` | uv `0.9.22`; unused `python-version: 3.12` input | align uv to `0.11.16` (Dockerfiles + local); drop/wire the unused input |
| local dev | `.venv` on 3.12 | `uv venv --python 3.14 && uv sync --extra private` (recreate) |
| `uv.lock` / `pyproject` | `requires-python >=3.12,<4` | **no change required**; optionally raise floor to `>=3.14` to match reality |
| `martin_sync.py` | `datetime.utcnow()` | `datetime.now(timezone.utc)` |

### ⚠ Alpine decision needed

`alpine-small-latest` is Alpine 3.24 / py 3.14.7 but ships **GDAL
3.14.0dev** (a development build — not production-grade). Pinned tags stop at
`alpine-small-3.13.3` (Alpine 3.23, py 3.12). Options:

1. **Switch the CI default distro to ubuntu** (pinned, py 3.14.4, GDAL 3.13.3
   stable) and leave alpine at 3.12 until `alpine-small-3.14.x` tags appear
2. Use `alpine-small-latest` accepting floating base + dev GDAL (not
   recommended — this is exactly the drift that broke builds in #148)
3. Wait for the pinned alpine 3.14 tags (GDAL 3.14.0 release expected soon
   given `latest` already carries 3.14.0dev)

Other notes: psycopg2-binary has no musllinux wheels — on alpine it builds
from source against `libpq-dev` (already in the builder), same as today.

## Rollout order (suggested)

1. `.python-version` + uv alignment + `martin_sync.py` utcnow fix; run full
   test suite on 3.14 locally (`inv tests`) and in CI (test.yml uses the
   shared action automatically)
2. ubuntu + debian Dockerfiles to 3.14; build & smoke-test both locally
3. Decide alpine path (above); if switching default distro, adjust
   `docker.yml` input default and docs
4. Merge with the `BUILD` label so the Docker workflow verifies in CI

## Cost estimate

Small: one-line pins per file, no dependency changes, no code changes beyond
the utcnow cleanup. The main work is the alpine decision + verification runs.

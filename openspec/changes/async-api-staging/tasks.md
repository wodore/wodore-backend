# Tasks: Staged async API migration

## 1. Stage 1 — Observability & availability (WSGI unchanged)

- [ ] 1.1 Add request/duration access-log middleware emitting one structlog event per response (method, path, status, duration ms; no tokens/bodies) with tests
- [ ] 1.2 Verify 200/304/4xx events appear in staging logs; no sensitive data leaks into events
- [ ] 1.2a Add lightweight `/healthz` endpoint (or designate an existing loop-served route) for probes
- [ ] 1.3 Consolidate gunicorn config: single repo-shipped config consumed by docker-compose and k8s; remove the inline k8s command (infra repo change: `wd-backend` deployment)
- [ ] 1.4 k8s: scale `wd-backend` to 2 replicas + PodDisruptionBudget `minAvailable: 1` + liveness probe (HTTP, `timeoutSeconds: 2`, `failureThreshold: 2`) (infra repo)
- [ ] 1.5 Move `migrate` out of `docker/django/gunicorn.sh` into a pre-deploy k8s Job; rehearse a rolling update in staging
- [ ] 1.6 Fix `wd-martin` CrashLoopBackOff in production (infra repo; diagnose 233-day crash loop)
- [ ] 1.7 Drop `psycopg2-binary` from `pyproject.toml`; `uv sync --extra private`, run `inv tests`
- [ ] 1.8 Deploy stage 1 to production; collect ≥1 week of duration baseline

## 2. Stage 2a — Django 6.1 baseline

- [ ] 2.1 Bump Django 6.0.3 → 6.1.x; verify psqlextra fork (`armonge/django-postgres-extra@feat/django-6`) on 6.1 (run test suite; vendor `PostgresViewModel` if the fork stalls)
- [ ] 2.2 Full `inv tests` + release process (changelog, image) for the 6.1 bump; deploy to staging

## 3. Stage 2b — ASGI with sync-core controllers

- [ ] 3.1 Add `uvicorn` + `psycopg[pool]` deps; wire `server.asgi` (gunicorn UvicornWorker, 1 worker/pod) into the consolidated config from 1.3
- [ ] 3.2 DB settings: `OPTIONS {"pool": True, "pool_size": 10}` (env-tunable), `CONN_MAX_AGE=0`, `CONN_HEALTH_CHECKS=True`; unit-test the env override
- [ ] 3.3 Convert controllers to the sync-core pattern: rename handler bodies to `_get_core`/`_post_core` etc., add thin `async def` wrappers via `sync_to_async` (start with `huts` list/detail, then remaining apps: geometries, meteo, availability, translations)
- [ ] 3.4 Async auth twin for `AuthBearer` (dmr `SyncOrAsyncAuth`); bridge or `httpx.AsyncClient` the introspection validator; short-TTL cache for introspection results
- [ ] 3.5 Make `EnvironmentHeadersMiddleware`, `LoggingContextVarsMiddleware`, `ApiVersionMiddleware` `async_capable` (`markcoroutinefunction`); audit third-party middleware (`corsheaders`, `csp`, `permissions-policy`, `whitenoise`) and record adapted ones via `django.request` debug log
- [ ] 3.6 Add event-loop lag watchdog (ASGI lifespan heartbeat, warn >250ms) with test
- [ ] 3.7 Enable ruff `ASYNC` lint rules; fix violations; wire into CI
- [ ] 3.8 Test: request-id/contextvar continuity through async controllers; contract suite + schemathesis green against ASGI application; ETag/304 and `Api-Version` downgrade behavior unchanged
- [ ] 3.9 Staging soak with `PYTHONASYNCIODEBUG=1`; load test with concurrent requests asserting isolation and pool behavior
- [ ] 3.10 Production rollout: canary one pod → both; compare duration logs against stage-1 baseline; rollback = previous image (WSGI)

## 4. Stage 3 — Optional, profile-gated native conversion

- [ ] 4.1 Analyze stage-2 duration/queueing data; identify endpoints where intra-request parallelism or native async would measurably help
- [ ] 4.2 Per-endpoint conversion to `aget()`/`async for` with before/after duration evidence (skip entirely if data shows no benefit)

# Tasks: Staged async API migration

> **Amended 2026-10-05** — struck items delivered by #254 (Django 6.1) and
> #259 (runtime switch, pool gate, lint, async og map). Pool policy and the
> app-level timeout were added/expanded from PoC findings (#252).

## 1. Stage 1 — Observability & availability (WSGI unchanged)

- [ ] 1.1 Add request/duration access-log middleware emitting one structlog event per response (method, path, status, duration ms; no tokens/bodies) with tests
- [ ] 1.2 Verify 200/304/4xx events appear in staging logs; no sensitive data leaks into events
- [ ] 1.2a Add lightweight `/healthz` endpoint (loop-served) for probes
- [ ] 1.3 ~~Consolidate gunicorn config~~ **half-done (#259)**: app module now in repo config — remaining: remove the inline k8s command in the infra repo so one source of truth applies everywhere
- [ ] 1.4 k8s: scale `wd-backend` to 2 replicas + PodDisruptionBudget `minAvailable: 1` + liveness probe (HTTP, `timeoutSeconds: 2`, `failureThreshold: 2`) (infra repo)
- [ ] 1.5 Move `migrate` out of the pod entrypoint into a pre-deploy k8s Job; rehearse a rolling update in staging
- [ ] 1.6 Fix `wd-martin` CrashLoopBackOff in production (infra repo; 235+ days, ~66k restarts)
- [ ] 1.7 Drop `psycopg2-binary` from `pyproject.toml`; `uv sync --extra private`, run `inv tests`
- [ ] 1.8 Deploy stage 1 to production; collect ≥1 week of duration baseline

## 2. Stage 2a — Django 6.1 baseline — **DONE**

- [x] 2.1 ~~Django 6.0.3 → 6.1.x~~ — delivered by #254 (incl. psqlextra fork on 6.1)
- [x] 2.2 ~~Release/deploy~~ — in production since #254

## 3. Stage 2b — ASGI flip prep (repo side; runtime groundwork landed in #259)

- [x] 3.1 ~~uvicorn dependency + `server.asgi` wiring~~ — delivered by #259 (`ASGI_ENABLED` switch, `uvicorn-worker`, `GUNICORN_WORKERS` env)
- [x] 3.2 ~~DB pool settings~~ — delivered by #259 as env gate (`POSTGRES_POOL`, `POSTGRES_POOL_SIZE`); **remaining policy work in 3.2a**
- [ ] 3.2a Pool policy from PoC findings: set `getconn` timeout ~2s (psycopg_pool `timeout` option), document per-worker `max_size` cap 4–5 (workers × max_size ≤ 15/pod); add a settings test
- [ ] 3.3 ~~Convert hot endpoints to sync-core~~ — **re-scoped**: default is no conversion (Django auto-adapts; measured equal-or-better); add sync-core wrappers only where dmr auth hooks need async (start with nothing; og map already native via #259)
- [ ] 3.4 Async auth twin for `AuthBearer` (dmr `SyncOrAsyncAuth`); bridge or `httpx.AsyncClient` the introspection validator; short-TTL cache for introspection results
- [ ] 3.5 Make `EnvironmentHeadersMiddleware`, `LoggingContextVarsMiddleware`, `ApiVersionMiddleware` `async_capable`; audit third-party middleware (`corsheaders`, `csp`, `permissions-policy`, `whitenoise`)
- [ ] 3.6 Add event-loop lag watchdog (ASGI lifespan heartbeat, warn >250ms) with test
- [ ] 3.6a **App-level request timeout** (gunicorn `--timeout` is inert under uvicorn workers — 52s request measured in #252); cancel + 503 contract
- [ ] 3.6b Wedge root-cause ticket: minimal reproducer for pool-checkout leak under concurrent per-request threads (one #252 run needed a restart); upstream or ours
- [x] 3.7 ~~Enable ruff `ASYNC` lint rules~~ — delivered by #259
- [ ] 3.8 Test: request-id/contextvar continuity through async controllers; contract suite + schemathesis green against ASGI application; ETag/304 and `Api-Version` downgrade behavior unchanged
- [ ] 3.9 Staging soak with `PYTHONASYNCIODEBUG=1`; load test with concurrent + slow-client + burst scenarios (the #252 lane scripts are a starting point)

## 4. Flip production to ASGI (gated on 1.8, 3.2a, 3.4–3.6b, 3.8, 3.9)

- [ ] 4.1 k8s: `ASGI_ENABLED=1`, `POSTGRES_POOL=1`, `GUNICORN_WORKERS=3`, remove inline command (infra repo); canary 1 pod → both; compare duration logs against the stage-1 baseline; rollback = previous image/env

## 5. Stage 3 — Optional, data-gated native conversion

- [ ] 5.1 Analyze post-flip duration/queueing data; convert an endpoint only where independent I/O would overlap (og map (#259) remains the template; blanket conversion was rejected by measurement — native burst8 13.0s vs sync-core 9.2s)

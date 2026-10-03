# Design: Staged async API migration

## Context

Production runs `wd-backend` as **1 replica / 1 pod** with `gunicorn -w 3 --timeout 30 --preload server.wsgi` (port 8008). The k8s command bypasses the repo's `docker/django/gunicorn_config.py` entirely — two diverged sources of truth. Observed load: ~3m CPU, 412Mi (limits 2Gi), ~600 log lines/24h dominated by scanner noise, zero `WORKER TIMEOUT` events, zero open app DB connections at rest (`CONN_MAX_AGE=60`). Successful 200 responses are not logged at all.

Stack facts established by research (see `_work` doc / session findings):
- dmr supports async endpoints natively (`endpoint.py` `is_async`) and ships `SyncAuth` / `AsyncAuth` / `SyncOrAsyncAuth` bases.
- Django 6.0.3 installed. Django 6.1 (Aug 2026) ships the async cache framework, async sessions, and dual-mode bundled middleware.
- The ORM never executes queries on the event loop: every `a*()` method is `sync_to_async(sync)()`. Django 6.1 guidance: async mode ⇒ `CONN_MAX_AGE` off, psycopg3 pool on, pool sized to target in-flight query concurrency.
- Transactions and the admin (Unfold) are sync-only, permanently.
- DB backend is `psqlextra.backend` (fork `armonge/django-postgres-extra@feat/django-6`), which wraps Django's psycopg3 backend.
- Background work (availability cronjobs, hut-services imports, admin) is and stays sync in separate processes.

## Goals / Non-Goals

**Goals:**
- Remove the 3-concurrent-request ceiling and the single-replica availability risk
- Make all API traffic observable (status + duration per request) before changing the runtime model
- Adopt ASGI with a **sync-core controller pattern**: async controller wrappers, unchanged sync handler cores — minimal bimodal surface, transactions intact
- Guard the event loop: structural (sync-core), lint (ruff `ASYNC`), runtime (loop-lag watchdog), topology (2 replicas + tight liveness probe)
- Keep the API contract byte-identical: `Api-Version`, ETags, error contract, OpenAPI schema unchanged

**Non-Goals:**
- Rewriting query code to `aget()`/`async for` (stage 3, optional, per-endpoint, profile-gated)
- Async background jobs, hut-services, or admin
- Websockets/SSE endpoints (this migration *enables* them; building them is future work)
- Redis cache / cross-process cache replacement (locmem deduplicates naturally with fewer processes; revisit only if cache hit rates matter later)

## Decisions

### D1: Sync-core controller pattern instead of full async conversion
Every dmr controller keeps its current handler logic as a private sync method; the endpoint becomes a thin `async def` that delegates via one `sync_to_async` bridge:

```python
async def get(self, parsed_path: Path[HutPath], parsed_query: Query[HutsQuery]):
    return await sync_to_async(self._get_core)(parsed_path, parsed_query)
```

Why: Django's documented recommendation ("restructure so the loop runs inside one `sync_to_async` crossing"); no `aget()` rewrite; `atomic()` keeps working inside cores; cores stay callable from sync tests/commands; concurrency ceiling equals pool size (identical to full conversion for sequential-query endpoints). Blocking calls are structurally confined to the bridged core. Alternative rejected: converting cores to a-variants now — large diff, breaks transactions, no measurable benefit at current traffic.

### D2: Deployment = gunicorn UvicornWorker × 1 worker per pod, 2 replicas
- `server.wsgi` → `server.asgi`; worker class `uvicorn.workers.UvicornWorker`, 1 worker process per pod (the event loop is the concurrency mechanism); replicas 1 → 2 with PDB `minAvailable: 1`.
- Consolidate config: one gunicorn config consumed by both docker-compose and k8s (k8s stops carrying its own inline command; `GUNICORN_WORKERS=1`, `WSGI_APPLICATION`/`ASGI_APPLICATION` env). Port stays 8008.
- `migrate` moves out of `docker/django/gunicorn.sh` into a k8s pre-deploy Job (helm/gitops change in the infra repo; this repo ships the compose/pre-sync equivalent + docs).

Why not more workers per pod: memory cost with no benefit (pool caps DB concurrency anyway); 2 pods bound the blast radius of a wedged loop.

### D3: Database = psycopg3 pool, `CONN_MAX_AGE=0`
`OPTIONS: {"pool": True, "pool_size": 10}` (psycopg_pool, ships via `psycopg[pool]`), `CONN_MAX_AGE=0` + `CONN_HEALTH_CHECKS=True`. Pool size 10 ⇒ up to 10 concurrent in-flight queries per pod ≈ 3× today's ceiling at half the pods' worker processes. Drop `psycopg2-binary` from pyproject (vestigial; nothing imports it; Django 6 removed psycopg2 support).

### D4: Auth — async twin, never introspect on the loop
`AuthBearer` gains an async counterpart using dmr's `SyncOrAsyncAuth` pattern. JWT validation is local CPU crypto and runs async; the legacy Zitadel introspection validator (network call) must run inside the bridge (`sync_to_async`) or use `httpx.AsyncClient` — a sync network call during auth would block the loop for every concurrent request. Add a cache (locmem, short TTL) for introspection results while touching it.

### D5: Middleware — custom three become `async_capable`; rest audited
`EnvironmentHeadersMiddleware`, `LoggingContextVarsMiddleware`, `ApiVersionMiddleware` get `async_capable = True` implementations (`markcoroutinefunction`). Bundled Django middleware is dual-mode on 6.1. Third-party (`corsheaders`, `csp`, `permissions-policy`, `whitenoise`) audited for `async_capable`; any sync one stays auto-adapted (thread hop per request, acceptable — verified counts logged via `django.request` "adapted" debug log at rollout).

`ApiVersionMiddleware` response transforms are pure response-processing and convert mechanically; its ETag-keying (version + registry hash) is unaffected.

### D6: Event-loop safety net
- ruff: enable `ASYNC` rules (blocking sleep/HTTP in async functions) in `[tool.ruff.lint]`.
- Loop-lag watchdog: ASGI-lifespan-started heartbeat task measuring `loop.time()` drift; warning log + metric-able event beyond 250ms.
- Liveness probe: HTTP probe against a loop-served endpoint (e.g. health endpoint), `timeoutSeconds: 2`, `failureThreshold: 2` — a wedged loop cannot answer, kubelet restarts the pod, second replica serves.
- Staging runs with `PYTHONASYNCIODEBUG=1` during rollout to surface slow callbacks.

### D7: Django 6.1 first
Stage 2 begins with the 6.0.3 → 6.1.x bump (async cache/sessions/middleware needed for D5; standard release-process PR, not mixed into the ASGI PR). Verify psqlextra fork on 6.1 (fork branch is already `feat/django-6`; pin moves may be needed).

### D8: Request/duration access logging (stage 1, independent of async)
Middleware emits one structlog event per completed response: method, path, status, duration, cache-hit/ETag outcome where cheap. `django.server` 200s stop being invisible. This is the measuring stick that gates stage 3 and validates stage 2 (before/after latency comparison).

## Risks / Trade-offs

- [Blocking call freezes a pod's loop] → structural (D1: blocking work lives inside bridges), lint (D6), watchdog + 2 replicas + aggressive liveness probe (D2/D6). Residual risk accepted: worst case = one pod restarts, not an outage.
- [psqlextra fork incompatible with 6.1] → verify before stage 2 starts; fallback: upstream pin or backend swap (only `PostgresViewModel` is used — cheap to vendor if the fork stalls).
- [dmr async path bugs] → sync-core keeps dmr surface minimal (endpoint dispatch only); full contract suite + schemathesis runs against ASGI in CI before rollout; staging soak with `PYTHONASYNCIODEBUG`.
- [Contextvar/log-context duplication across the bridge] → `LoggingContextVarsMiddleware` converted in D5 and covered by explicit tests asserting request-id continuity through an async controller.
- [Pool exhaustion latency cliffs] → pool 10/pod with health checks; request-duration logging (D8) makes queueing visible; pool size is a one-line env-backed tune.
- [Rolling update stalls with 2 replicas if migrate stays in-entrypoint] → D2 migrate Job; verified by rehearsing the rollout in staging.
- [GIL contention with many active threads] → pool caps threads per pod at ~10; far below contention territory.
- [`wd-martin` fix out of repo scope] → tracked as stage-1 item in the infra repo; not a blocker for stages 2/3 of this change.

## Migration Plan

1. **Stage 1** (ship independently, sync runtime unchanged): D8 logging; k8s replicas+PDB+probe; migrate Job; martin fix; psycopg2-binary cleanup; gunicorn config consolidation (still WSGI). Deploy, observe real traffic baseline for ≥1 week.
2. **Stage 2a**: Django 6.1 bump PR (release process, its own changelog entry).
3. **Stage 2b**: ASGI PR — D1–D6. Roll out staging → production canary (1 pod) → both pods. Rollback = revert deployment to previous image (WSGI config still present in repo history); no data/schema changes involved.
4. **Stage 3** (optional, only if profiling shows need): per-endpoint native conversion, decided endpoint-by-endpoint with duration data from D8.

## Open Questions

- Kubernetes manifests live outside this repo (flux/gitops in the infra project) — confirm where the `wd-backend` deployment + migrate Job changes land and who applies them.
- Should the health/liveness endpoint be a new lightweight `/healthz` on the API (currently no such route serves the loop directly)?
- Pool size 10 vs larger — decided by stage-1 baseline data (current traffic suggests 10 is generous).

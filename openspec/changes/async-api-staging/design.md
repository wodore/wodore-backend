# Design: Staged async API migration

> **Amended 2026-10-05.** D7 (Django 6.1) is delivered (#254); D1/D2/D3/D6
> are partially delivered or measured — see each decision's status line.
> Measurements referenced below were taken in the PoC lane
> ([#252](https://github.com/wodore/wodore-backend/pull/252)) on the same
> data as production-shape WSGI.

## Context

Production runs `wd-backend` as **1 replica / 1 pod** with an inline k8s
gunicorn command (`-w 3 --timeout 30 --preload`, WSGI, port 8008) that
bypasses the repo config. Observed (2026-10-05): ~idle traffic, no access
logging for 2xx, zero worker timeouts, `wd-martin` CrashLoopBackOff since
235 days, `psycopg2-binary` still pinned.

Landed on main since the original proposal: **Django 6.1** (#254 — async
cache framework, async sessions, dual-mode bundled middleware), **#259**
(`ASGI_ENABLED` runtime switch via `gunicorn_config.py` (`wsgi_app`,
`uvicorn_worker.UvicornWorker`), env-gated psycopg3 pool
(`POSTGRES_POOL`/`POSTGRES_POOL_SIZE`, `CONN_MAX_AGE=0` while enabled),
ruff `ASYNC` rules, and the og static-map endpoint as a native-async
showcase: tiles+marker overlap in a TaskGroup, decode/composite bridged).

PoC facts that shaped the amendments below (see #252 for details):
- ORM async is thread-bridging per query (`aget = await
  sync_to_async(get)()`); native conversion measured **worse** under load
  (hut list burst8: 13.0s native vs 9.2–9.9s sync-core at ×1 worker);
  serializer lazy N+1 loads crash on the loop (`SynchronousOnlyOperation`)
- **ASGI ×3 workers beats every other config measured**: sustained 16
  clients 17.9 req/s vs 5.1 (prod WSGI ×3) and 6.4 (ASGI ×1); burst8 hut
  list 4.8s vs 12–27s (WSGI); survives slow readers and the 2.85 MB full
  list (WSGI: worker killed at `--timeout 30` → hard 500)
- Pool exhaustion wedge: 40× burst → 30s `getconn` timeouts → 500s; one
  run never recovered (idle-in-PG conns, pool exhausted, restart needed);
  steady-state returns work fine
- GIL: CPU-heavy endpoints scale linearly per process regardless of
  runtime — process count is the CPU parallelism dial

## Goals / Non-Goals

**Goals:**
- Remove the 3-concurrent-request ceiling and the single-replica availability risk
- Make all API traffic observable (status + duration per request) before flipping runtimes
- Flip production to ASGI (measured best config) behind stage gates
- Guard the event loop: auth off the loop, async-capable middleware, app-level request timeout, pool policy, watchdog

**Non-Goals:**
- Converting endpoint handlers to native async (rejected by measurement; og map (#259) stays the exception that proves the rule — independent I/O)
- Async background jobs, hut-services, or admin
- Websockets/SSE endpoints (enabled by the runtime, not built here)
- Redis/shared cache (locmem deduplicates once process count drops; revisit if hit rates matter)

## Decisions

### D1: Sync-core pattern as the default — **validated by PoC**
Thin `async def` controller delegating via one `sync_to_async` bridge to an unchanged sync core; transactions keep working; cores stay callable from sync contexts. PoC: contract byte-identical, no `aget()` needed, bursts better than native-async. Most endpoints need **no change at all** (Django auto-adapts sync views under ASGI — measured on geojson/list endpoints in #259). Status: pattern documented; endpoint conversion only where dmr auth hooks or explicit control demand it.

### D2: Deployment = ASGI ×3 uvicorn workers per pod, 2 replicas — **amended by measurement**
Original: 1 worker/pod × 2 replicas. Measured: 3 event loops dominate (17.9 vs 6.4 req/s sustained; GIL-parallel CPU across processes; loop-wedge blast radius ⅓ per pod). Config is on main (#259: `ASGI_ENABLED=1`, `GUNICORN_WORKERS=3`); production flip is a k8s env/command change gated on stage-2 tasks. Alternative rejected: ASGI ×1 (slower, single loop wedge = whole pod).

### D3: Pool with short timeout and per-worker cap — **amended by PoC finding**
`OPTIONS["pool"] = {"min_size": 2, "max_size": N}` (env-tunable since #259) + `CONN_MAX_AGE=0`. Amendments: set a **~2s getconn timeout** (default 30s produced wedged 500s under burst) and cap per-worker `max_size` at 4–5 (≤15 conns/pod; measured 3 pools × 10 = 20 conns under load). Root-cause the leaked-checkout wedge (one PoC run never recovered) before the prod flip. Format note: pool options must be a dict — flat keys leak into connect kwargs (`invalid connection option`).

### D4: Auth — async twin, never introspect on the loop — **open (stage 2)**
`AuthBearer` async counterpart via dmr `SyncOrAsyncAuth`; JWT verification is local CPU; the legacy Zitadel introspection validator must bridge or use `httpx.AsyncClient` + a short-TTL cache. A sync network call during auth blocks the loop for every concurrent request.

### D5: Middleware — custom three `async_capable` — **open (stage 2), cheaper since Django 6.1**
`EnvironmentHeadersMiddleware`, `LoggingContextVarsMiddleware`, `ApiVersionMiddleware` get `async_capable = True` (`markcoroutinefunction`). Django 6.1's bundled middleware (sessions, cache) is dual-mode natively. Third-party audit (`corsheaders`, `csp`, `permissions-policy`, `whitenoise`); adapted ones are acceptable (thread hop per request).

### D6: Event-loop safety net — **lint delivered (#259); watchdog + timeout open**
Delivered: ruff `ASYNC` rules in CI. Open: loop-lag watchdog (lifespan heartbeat, warn >250ms), liveness probe with `timeoutSeconds: 2` (a wedged loop cannot answer → kubelet restarts; the second replica serves), **app-level request timeout** (gunicorn `--timeout` is inert under uvicorn workers — measured 52s request with no kill), and `PYTHONASYNCIODEBUG=1` staging soak.

### D7: Django 6.1 first — **delivered by #254**

### D8: Request/duration access logging — **open (stage 1, unchanged)**
One structlog event per completed response (method, path, status, duration; no tokens/bodies), deployed under WSGI to build a ≥1-week baseline before the ASGI flip. This is also the measuring stick for stage-3 gating.

## Risks / Trade-offs

- [Blocking call freezes a loop] → lint (shipped), watchdog + probe + 2 replicas (stage 1/2), blast radius ⅓ per pod at ×3 workers
- [Pool exhaustion wedge under burst] → short pool timeout + cap (D3) + root-cause ticket **blocks the prod flip**
- [No request timeout under ASGI] → app-level timeout task **blocks the prod flip** (52s measured worst case)
- [psqlextra fork on 6.1] → resolved: fork runs on Django 6.1 in production since #254
- [dmr async path bugs] → sync-core keeps dmr surface minimal; og map (#259) exercises the async dispatch in prod traffic already
- [Contextvar/log-context across the bridge] → `LoggingContextVarsMiddleware` conversion + continuity tests (stage 2)
- [`wd-martin` fix out of repo scope] → infra-repo item; not a blocker for stage 2
- [CPU-bound endpoints stay GIL-linear] → accepted; process count (×3 workers ×2 replicas) is the CPU dial; ETag/category work already landed (#257) to cut per-request CPU

## Migration Plan

1. **Stage 1** (WSGI unchanged): D8 logging; k8s replicas+PDB+probe; migrate Job; martin fix; psycopg2-binary cleanup; drop inline k8s gunicorn command (config is single source since #259). Baseline ≥1 week.
2. **Stage 2a — done** (#254).
3. **Stage 2b — flip prep** (repo): auth twin (D4), middleware (D5), watchdog + app timeout (D6), pool timeout/cap (D3), wedge root-cause ticket. Staging soak with `PYTHONASYNCIODEBUG=1`; load test incl. slow-client and burst scenarios.
4. **Flip**: `ASGI_ENABLED=1`, `POSTGRES_POOL=1` (timeout 2s, `max_size` 4–5), `GUNICORN_WORKERS=3`, 2 replicas. Canary 1 pod → both. Rollback = previous image/env (WSGI path still shipped and tested).
5. **Stage 3** (optional): per-endpoint native conversion only with duration-data justification.

## Open Questions

- k8s manifests live in the infra (flux/gitops) repo — confirm owner for the deployment changes + migrate Job.
- Health/liveness endpoint: add `/healthz` (loop-served) or reuse an existing route?
- Pool wedge root cause: upstream (Django 6.1 / psycopg_pool) vs our combination — needs a minimal reproducer.

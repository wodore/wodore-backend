# Proposal: Staged async API migration

> **Amended 2026-10-05** after the PoC (#252) and the merged runtime work
> ([#259](https://github.com/wodore/wodore-backend/pull/259)): Django 6.1
> landed via #254, the runtime switch / pool / lint groundwork and the async
> og-map showcase shipped in #259. This proposal now covers the **remaining**
> work only; delivered items are struck through in tasks.md.

## Why

The public API runs on WSGI with 3 gunicorn sync workers on a single Kubernetes replica — a hard concurrency ceiling of 3 in-flight requests, duplicated per-worker caches, no visibility into successful requests, and no capacity story for growth (slow mobile clients pin workers; spikes queue at the socket). Production checks (2026-10-05) confirm: 1 replica, ~idle traffic, `wd-martin` still in CrashLoopBackOff, no access logging, `psycopg2-binary` still pinned. The runtime is now async-ready on main (#259) but production has not flipped, and the async-specific gaps (auth, middleware, timeouts, pool policy) are open.

## What Changes

- **Stage 1 — Observability & availability (WSGI unchanged, valuable regardless of async):**
  - Structured request/duration access logging for all responses (today 200s are invisible in production logs)
  - Kubernetes: scale `wd-backend` to 2 replicas with a PodDisruptionBudget and a tight HTTP liveness probe
  - Move `migrate` out of the pod entrypoint into a pre-deploy job so rolling updates actually roll
  - Fix `wd-martin` CrashLoopBackOff (running 235+ days)
  - Retire the inline k8s gunicorn command (drifts from the repo config; #259 moved the app module into the config so the k8s command can go)
  - Drop vestigial `psycopg2-binary` dependency
- **Stage 2 — ASGI rollout (runtime groundwork landed in #259):**
  - Flip production to `ASGI_ENABLED=1` + `POSTGRES_POOL=1` + `GUNICORN_WORKERS=3` (uvicorn workers) once the stage-2 gates below pass
  - Async auth twin for `BearerSyncAuth` (dmr `SyncOrAsyncAuth`); OIDC introspection never runs on the event loop
  - Custom middlewares (`EnvironmentHeadersMiddleware`, `LoggingContextVarsMiddleware`, `ApiVersionMiddleware`) become `async_capable`; audit third-party middleware
  - **App-level request timeout** (uvicorn workers heartbeat → gunicorn `--timeout` is inert under ASGI — measured in #252: the 2.85 MB full list runs 52s with no kill)
  - **Pool policy**: short `getconn` timeout (~2s), per-worker cap (`max_size` 4–5 → ≤15 conns/pod) — the PoC measured pool-exhaustion wedging under a 40× burst with the 30s default
  - Loop-lag watchdog (ASGI lifespan heartbeat, warn >250ms)
  - Wedge root-cause ticket: pool checkouts leaked under concurrent per-request threads in one PoC run (process needed restart)
- **Stage 3 — Optional, per-endpoint native conversion** — only where independent I/O overlaps (the og map already did: #259). The PoC **rejected** blanket native conversion: hut-list native-async burst8 was 13.0s vs 9.2–9.9s sync-core; sync-core/no-conversion is the default pattern.

No API contract changes; `Api-Version` semantics, ETags, error contracts, and OpenAPI schema stay identical (verified in #252/#259 across both runtimes).

## Capabilities

### New Capabilities
- `async-api-runtime`: end-state requirements for ASGI operation (sync-core default, event-loop safety, watchdog, pool policy for async mode, async-capable middleware, unchanged contract)
- `api-observability`: request/duration access logging for all API responses with loop-lag health signal
- `api-deployment-ha`: multi-replica topology, wedged-loop-catching liveness probe, migration job, single-source gunicorn configuration

### Modified Capabilities
(none)

## Impact

- **Code:** `server/apps/api/auth.py` (async twin), `server/middleware/` + `server/settings/components/logging.py` (async-capable, access logging), `server/settings/components/databases.py`-adjacent pool policy (env-tunable since #259), app-level timeout middleware/util
- **Infra (k8s, outside this repo):** `wd-backend` deployment (replicas, probes, command removal, ASGI env), migrate job, `wd-martin` fix
- **Already landed:** runtime switch, uvicorn-worker dep, env-gated psycopg3 pool, ruff `ASYNC` rules, async og map (#259); Django 6.1 (#254)
- **Risk:** flipping prod to ASGI inverts timeout semantics and changes DB connection behavior — both are gated tasks above; stage 1 must land first (observability + 2 replicas bound every blast radius)

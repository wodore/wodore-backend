# Proposal: Staged async API migration

## Why

The public API runs on WSGI with 3 gunicorn sync workers on a single Kubernetes replica — a hard concurrency ceiling of 3 in-flight requests, duplicated per-worker caches, and no capacity story for growth (slow mobile clients pin workers; spikes queue at the socket). Production logs confirm no current pain (near-idle traffic), so this is a deliberate platform investment for efficiency, headroom, and future capabilities (SSE/streaming), executed in independently shippable stages with observability and availability fixes landing first.

## What Changes

- **Stage 1 — Observability & availability (valuable without async):**
  - Structured request/duration access logging for all responses (today 200s are invisible in production logs)
  - Kubernetes: scale `wd-backend` to 2 replicas with a PodDisruptionBudget and a tight HTTP liveness probe
  - Move `migrate` out of the pod entrypoint into a pre-deploy job so rolling updates actually roll
  - Fix `wd-martin` CrashLoopBackOff (running 233 days) and the repo-vs-k8s gunicorn config drift (two sources of truth)
  - Drop vestigial `psycopg2-binary` dependency
- **Stage 2 — ASGI deployment with sync-core controllers:**
  - Django 6.0.3 → 6.1.x upgrade (unblocks async cache framework, async sessions, dual-mode bundled middleware)
  - Server switches to `server.asgi` with uvicorn workers; consolidate gunicorn config into one source of truth
  - Database: enable psycopg3 pool (`"pool": True`), disable `CONN_MAX_AGE`, size pool for target concurrency
  - dmr controllers become thin `async def` wrappers delegating to unchanged sync cores via `sync_to_async` (no `aget()` rewrite, transactions keep working)
  - Async auth twin for `BearerSyncAuth` (dmr `SyncOrAsyncAuth` pattern); OIDC introspection path never runs on the event loop
  - Custom middlewares (`EnvironmentHeadersMiddleware`, `LoggingContextVarsMiddleware`, `ApiVersionMiddleware`) become `async_capable`; loop-lag watchdog added
  - Lint guard: enable ruff `ASYNC` rules to catch blocking calls in async functions
- **Stage 3 — Optional, per-endpoint selective conversion** (only if profiling justifies it): convert hot handlers from the sync-core bridge to native `aget()`/`async for` variants for intra-request parallelism.

No API contract changes in any stage; `Api-Version` semantics, ETags, error contracts, and OpenAPI schema stay identical.

## Capabilities

### New Capabilities
- `async-api-runtime`: ASGI deployment, sync-core controller execution model, event-loop safety guards (lint + watchdog), and database pool configuration for async mode
- `api-observability`: request/duration access logging for all API responses with loop-lag health signal
- `api-deployment-ha`: multi-replica deployment topology, liveness/readiness probe design, migration job, and single-source gunicorn configuration

### Modified Capabilities
(none — no spec-level behavior of existing capabilities changes)

## Impact

- **Code:** `server/apps/api/` controllers (wrapper pattern), `server/apps/api/auth.py` (async auth twin), `server/middleware/` + `server/settings/components/logging.py` (async-capable, request logging), `server/settings/components/databases.py` (pool), `pyproject.toml` (Django 6.1, uvicorn, drop psycopg2-binary, ruff ASYNC rules)
- **Infra (k8s, outside this repo):** `wd-backend` deployment (replicas, probes, command/env), migrate job, `wd-martin` fix — coordinated with the cluster config in the infra repo
- **Dependencies:** django 6.1.x, uvicorn (+gunicorn UvicornWorker), psqlextra fork compat with 6.1
- **Risk:** stage 2 changes the process model (3 workers → 1 event loop × 2 replicas); failure-mode inversion (a blocking call on the loop stalls a pod) is mitigated structurally (sync-core), by lint, by watchdog, and by the 2-replica + liveness-probe topology from stage 1

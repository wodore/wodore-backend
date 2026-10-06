# Spec Delta: api-deployment-ha

## ADDED Requirements

### Requirement: Multi-replica API deployment
The `wd-backend` Kubernetes deployment SHALL run at least 2 replicas with a PodDisruptionBudget (`minAvailable: 1`) so that one pod can fail, restart, or update while the other serves traffic.

#### Scenario: Single pod failure keeps API available
- **WHEN** one backend pod crashes or is restarted by the kubelet
- **THEN** the API remains available through the remaining replica

#### Scenario: Rolling update proceeds without downtime
- **WHEN** a new backend image version is rolled out
- **THEN** pods are replaced one at a time and the API serves requests throughout

### Requirement: Liveness probe catches a wedged event loop
Each backend pod SHALL have an HTTP liveness probe against an endpoint served by the request runtime, with a timeout of 2 seconds and `failureThreshold: 2`, so that a pod whose event loop (ASGI) or workers (WSGI) stop answering is restarted quickly.

#### Scenario: Wedged loop triggers restart
- **WHEN** a pod's request runtime stops answering requests entirely
- **THEN** the liveness probe fails twice within seconds and the kubelet restarts the pod while the other replica serves

### Requirement: Migrations run as a pre-deploy job
Database migrations SHALL NOT run in the application pod entrypoint. They SHALL run in a separate pre-deploy Kubernetes job that completes before new pods roll out, so replicas never serialize on boot-time migrations.

#### Scenario: Deploy with schema changes
- **WHEN** a release containing new migrations is deployed
- **THEN** the migration job completes before the new pods start, and rolling update proceeds without pods waiting on each other

### Requirement: Single source of truth for server configuration
The gunicorn/uvicorn server configuration SHALL be defined exactly once (repo-shipped config consumed by every environment). The Kubernetes deployment SHALL NOT carry a divergent inline gunicorn command.

#### Scenario: Kubernetes uses the repo configuration
- **WHEN** the backend pod starts in any environment
- **THEN** its worker class, worker count, timeouts, and ports come from the shared configuration, and changing that file changes behavior everywhere consistently

### Requirement: Cache duplication reduces with process consolidation
Moving from 3 sync workers to 1 async process per pod SHALL reduce per-pod LocMemCache duplication from 3 independent caches to 1, improving cache hit rate without code changes to the cache layer.

#### Scenario: One cache per pod
- **WHEN** two requests hit the same pod in ASGI mode
- **THEN** the second request benefits from the first request's locmem cache entries (no per-worker cache duplication)

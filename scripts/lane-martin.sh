#!/usr/bin/env bash
# Start/stop a lane-scoped Martin (docker, same image as docker-compose) that
# serves the LANE database, so tile work can happen inside a worktree.
#
#   scripts/lane-martin.sh start    # run on the workz port (PORT+1), wait until ready
#   scripts/lane-martin.sh stop     # docker rm -f (workz reap cannot remove containers)
#   scripts/lane-martin.sh status   # running? URL? target DB?
#
# Why docker (not a local martin binary): identical image and config to the
# shared compose instance (ghcr.io/maplibre/martin, martin_sync config,
# --webui enable-for-all). The container joins the compose postgres network
# and reaches the shared dev postgres by container name; DATABASE_URL points
# at the LANE DB (name from the workz-managed .env.local). The martin port is
# PORT+1 — the lane dev server (`workz run`) uses PORT — and
# scripts/lane-run.sh injects MARTIN_TILE_URL=http://localhost:<PORT+1>
# accordingly.
#
# Credentials (POSTGRES_USER/PASSWORD) come from infisical, like every other
# command in this repo: the docker command runs inside the infisical wrapper,
# so secrets never leave the process environment.
set -euo pipefail

NETWORK="${MARTIN_NETWORK:-wodore-backend_postgresnet}"
IMAGE="${MARTIN_IMAGE:-ghcr.io/maplibre/martin:latest}"
DB_HOST="${MARTIN_DB_HOST:-django-local-postgis}"

if [ ! -f .env.local ]; then
    echo "lane-martin: no .env.local here — run 'workz sync . --isolated' first (or: not a workz worktree)" >&2
    exit 1
fi
DB_NAME="$(sed -n 's/^DB_NAME=//p' .env.local)"
PORT_BASE="$(sed -n 's/^PORT=//p' .env.local)"
if [ -z "$DB_NAME" ] || [ -z "$PORT_BASE" ]; then
    echo "lane-martin: DB_NAME/PORT missing from .env.local (workz managed block missing?)" >&2
    exit 1
fi
MARTIN_PORT="${MARTIN_PORT:-$((PORT_BASE + 1))}"
CONTAINER="martin-lane-${DB_NAME}"

case "${1:-}" in
start)
    if docker inspect "$CONTAINER" >/dev/null 2>&1; then
        echo "lane-martin: already running at http://localhost:${MARTIN_PORT} (DB: ${DB_NAME}, container: ${CONTAINER})"
        exit 0
    fi
    if [ ! -f martin_sync/config/martin.yaml ]; then
        echo "lane-martin: no martin_sync/config/martin.yaml — run 'scripts/sync-martin.sh' first" >&2
        exit 1
    fi
    infisical run --env=dev --path /backend --silent --log-level warn -- \
        env DB_NAME="$DB_NAME" DB_HOST="$DB_HOST" NETWORK="$NETWORK" IMAGE="$IMAGE" \
            MARTIN_PORT="$MARTIN_PORT" CONTAINER="$CONTAINER" \
        bash -c 'docker run -d --rm --name "$CONTAINER" \
            --network "$NETWORK" \
            -e DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${DB_HOST}:5432/${DB_NAME}" \
            -e MARTIN_SYNC_MOUNT=/martin_sync \
            -v "$(pwd)/martin_sync:/martin_sync:ro" \
            -p "${MARTIN_PORT}:3000" \
            "$IMAGE" --config /martin_sync/config/martin.yaml --webui enable-for-all' >/dev/null
    # Bounded readiness wait: martin answers on /catalog once the DB connection is up.
    for _ in $(seq 1 30); do
        if curl -sf "http://localhost:${MARTIN_PORT}/catalog" >/dev/null; then
            echo "lane-martin: ready at http://localhost:${MARTIN_PORT} (DB: ${DB_NAME}, container: ${CONTAINER})"
            exit 0
        fi
        sleep 1
    done
    echo "lane-martin: container started but not ready within 30s — check: docker logs ${CONTAINER}" >&2
    exit 1
    ;;
stop)
    docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
    echo "lane-martin: stopped (${CONTAINER})"
    ;;
status)
    if docker inspect "$CONTAINER" >/dev/null 2>&1; then
        echo "lane-martin: running — http://localhost:${MARTIN_PORT} (DB: ${DB_NAME}, container: ${CONTAINER})"
    else
        echo "lane-martin: not running (start with: scripts/lane-martin.sh start)"
        exit 1
    fi
    ;;
*)
    echo "usage: $0 start|stop|status" >&2
    exit 2
    ;;
esac

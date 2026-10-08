#!/usr/bin/env bash
# Start/stop a lane-scoped Martin (docker, same image as docker-compose) that
# serves the LANE database, so tile work can happen inside a worktree.
#
#   scripts/lane-martin.sh start    # run on the workz port PORT_END, wait until ready
#   scripts/lane-martin.sh stop     # docker rm -f (workz reap cannot remove containers)
#   scripts/lane-martin.sh status   # running? URL? target DB?
#
# Why docker (not a local martin binary): identical image and config to the
# shared compose instance (ghcr.io/maplibre/martin, martin_sync config,
# --webui enable-for-all). The container joins the compose postgres network
# and reaches the shared dev postgres by container name; DATABASE_URL points
# at the LANE DB (name from the workz-managed .env.local). The martin port is
# PORT_END — the top of the workz range (the dev server uses PORT and workz
# itself advertises REDIS_URL at PORT+1, so PORT+1 is NOT free) — and
# scripts/lane-run.sh injects MARTIN_TILE_URL=http://localhost:<PORT_END>
# accordingly.
#
# A second container (nginx:alpine) runs the terrain proxy_cache from
# tile_server/nginx/nginx.conf.template on PORT_END-1 (inside the lane's
# workz range, unallocated by workz): Martin does NOT cache its postprocessed
# terrain output (hillshade/contours), so warm tiles need this cache in
# front — same config as the compose `martin-cache` service (profile
# terrain-cache). `stop` removes both containers but keeps the cache volume
# (martin-cache-lane-<db>), so restarts stay warm; `docker volume rm` it to
# force cold-cache timing runs.
#
# Credentials (POSTGRES_USER/PASSWORD) come from infisical, like every other
# command in this repo: the docker command runs inside the infisical wrapper,
# so secrets never leave the process environment.
set -euo pipefail

NETWORK="${MARTIN_NETWORK:-wodore-backend_postgresnet}"
IMAGE="${MARTIN_IMAGE:-ghcr.io/maplibre/martin:latest}"
NGINX_IMAGE="${MARTIN_CACHE_IMAGE:-nginx:alpine}"
DB_HOST="${MARTIN_DB_HOST:-django-local-postgis}"

if [ ! -f .env.local ]; then
    echo "lane-martin: no .env.local here — run 'workz sync . --isolated' first (or: not a workz worktree)" >&2
    exit 1
fi
DB_NAME="$(sed -n 's/^DB_NAME=//p' .env.local)"
PORT_END="$(sed -n 's/^PORT_END=//p' .env.local)"
if [ -z "$DB_NAME" ] || [ -z "$PORT_END" ]; then
    echo "lane-martin: DB_NAME/PORT_END missing from .env.local (workz managed block missing?)" >&2
    exit 1
fi
MARTIN_PORT="${MARTIN_PORT:-$PORT_END}"
CONTAINER="martin-lane-${DB_NAME}"
CACHE_PORT="${MARTIN_CACHE_PORT:-$((PORT_END - 1))}"
CACHE_CONTAINER="martin-cache-lane-${DB_NAME}"
CACHE_VOLUME="martin-cache-lane-${DB_NAME}"

is_running() {
    [ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null || true)" = "true" ]
}

cache_is_running() {
    [ "$(docker inspect -f '{{.State.Running}}' "$CACHE_CONTAINER" 2>/dev/null || true)" = "true" ]
}

start_cache() {
    if cache_is_running; then
        echo "lane-martin: terrain cache already up at http://localhost:${CACHE_PORT}"
        return 0
    fi
    if [ ! -f tile_server/nginx/martin-terrain-cache.conf.template ]; then
        echo "lane-martin: tile_server/nginx/martin-terrain-cache.conf.template missing — skipping cache" >&2
        return 0
    fi
    docker rm -f "$CACHE_CONTAINER" >/dev/null 2>&1 || true
    # No infisical wrapper needed: no secrets, the upstream is the lane
    # martin container, reached by container name on the shared network.
    docker run -d --rm --name "$CACHE_CONTAINER" \
        --network "$NETWORK" \
        -e MARTIN_UPSTREAM="${CONTAINER}:3000" \
        -v "$(pwd)/tile_server/nginx:/etc/nginx/templates:ro" \
        -v "$(pwd)/tile_server/nginx/default.conf.disabled:/etc/nginx/conf.d/default.conf:ro" \
        -v "${CACHE_VOLUME}:/var/cache/nginx" \
        -p "${CACHE_PORT}:80" \
        "$NGINX_IMAGE" >/dev/null
    for _ in $(seq 1 15); do
        if curl -sf "http://localhost:${CACHE_PORT}/catalog" >/dev/null; then
            echo "lane-martin: terrain cache ready at http://localhost:${CACHE_PORT} (X-Cache-Status: HIT/MISS)"
            return 0
        fi
        sleep 1
    done
    echo "lane-martin: terrain cache started but not ready within 15s — check: docker logs ${CACHE_CONTAINER}" >&2
    return 1
}

case "${1:-}" in
start)
    if is_running; then
        echo "lane-martin: already running at http://localhost:${MARTIN_PORT} (DB: ${DB_NAME}, container: ${CONTAINER})"
        start_cache
        exit 0
    fi
    # A stale exited/created container with our name would block docker run.
    docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
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
    martin_ready=false
    for _ in $(seq 1 30); do
        if curl -sf "http://localhost:${MARTIN_PORT}/catalog" >/dev/null; then
            martin_ready=true
            break
        fi
        sleep 1
    done
    if [ "$martin_ready" != true ]; then
        echo "lane-martin: container started but not ready within 30s — check: docker logs ${CONTAINER}" >&2
        exit 1
    fi
    echo "lane-martin: ready at http://localhost:${MARTIN_PORT} (DB: ${DB_NAME}, container: ${CONTAINER})"
    start_cache
    ;;
stop)
    docker rm -f "$CACHE_CONTAINER" >/dev/null 2>&1 || true
    docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
    echo "lane-martin: stopped (${CONTAINER}, ${CACHE_CONTAINER}; cache volume ${CACHE_VOLUME} kept)"
    ;;
status)
    code=0
    if is_running; then
        echo "lane-martin: running — http://localhost:${MARTIN_PORT} (DB: ${DB_NAME}, container: ${CONTAINER})"
    else
        echo "lane-martin: not running (start with: scripts/lane-martin.sh start)"
        code=1
    fi
    if cache_is_running; then
        echo "lane-martin: terrain cache running — http://localhost:${CACHE_PORT} (${CACHE_CONTAINER})"
    else
        echo "lane-martin: terrain cache not running"
    fi
    exit "$code"
    ;;
*)
    echo "usage: $0 start|stop|status" >&2
    exit 2
    ;;
esac

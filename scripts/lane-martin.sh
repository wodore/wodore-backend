#!/usr/bin/env bash
# Start/stop a lane-scoped tile stack (docker, same images as docker-compose)
# that serves the LANE database, so tile work can happen inside a worktree.
#
#   scripts/lane-martin.sh start    # router on the workz port + martin behind it
#   scripts/lane-martin.sh stop     # docker rm -f both (workz reap cannot remove containers)
#   scripts/lane-martin.sh status   # running? URL? target DB?
#
# Topology mirrors the shared dev compose: martin itself is compose-internal
# (NO host port); the nginx tile-router (tile_server/tile-router.conf.template)
# is the single published origin on the workz port PORT_END. This matters for
# the .mlt URL space: the router strips the suffix and sends the MLT accept
# header — direct martin access would 301 .mlt URLs back to MVT (see AGENTS.md
# "Map layers / MLT"). Without the router, lane-served styles carrying .mlt
# tiles templates would break MLT-decoding clients in lane dev.
#
# Why docker (not a local martin binary): identical image and config to the
# shared compose instance (ghcr.io/maplibre/martin, martin_sync config,
# --webui enable-for-all). Both containers join the compose postgres network
# (martin reaches the shared dev postgres by container name; the router also
# joins the compose default network for /raster/* → mapproxy parity);
# DATABASE_URL points at the LANE DB (name from the workz-managed .env.local).
# The router publishes PORT_END — the top of the workz range (the dev server
# uses PORT and workz itself advertises REDIS_URL at PORT+1, so PORT+1 is NOT
# free) — and scripts/lane-run.sh injects
# MARTIN_TILE_URL=http://localhost:<PORT_END> accordingly.
#
# Credentials (POSTGRES_USER/PASSWORD) come from infisical, like every other
# command in this repo: the docker command runs inside the infisical wrapper,
# so secrets never leave the process environment. When infisical is
# unavailable, the compose-file defaults (wodore/wodore, public in
# docker-compose.yml) apply — dev-stack-only convenience, identical to how
# docker-compose.yml itself defaults them.
set -euo pipefail

NETWORK="${MARTIN_NETWORK:-wodore-backend_postgresnet}"
DEFAULT_NETWORK="${MARTIN_DEFAULT_NETWORK:-wodore-backend_default}"
IMAGE="${MARTIN_IMAGE:-ghcr.io/maplibre/martin:latest}"
ROUTER_IMAGE="${MARTIN_ROUTER_IMAGE:-nginx:1.27-alpine}"
DB_HOST="${MARTIN_DB_HOST:-django-local-postgis}"
MAPPROXY_HOST="${MARTIN_MAPPROXY_HOST:-django-local-mapproxy:80}"

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
ROUTER="tile-router-lane-${DB_NAME}"

is_running() {
    [ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null || true)" = "true" ]
}

router_running() {
    [ "$(docker inspect -f '{{.State.Running}}' "$ROUTER" 2>/dev/null || true)" = "true" ]
}

run_docker() {
    # Prefer infisical for credentials; fall back to the compose defaults
    # (dev-stack only) when it is unavailable (e.g. expired login). The
    # probe must never hang on an interactive login prompt.
    if timeout 10 infisical run --env=dev --path /backend --silent --log-level warn -- true </dev/null >/dev/null 2>&1; then
        infisical run --env=dev --path /backend --silent --log-level warn -- "$@"
    else
        echo "lane-martin: infisical unavailable — using docker-compose default credentials" >&2
        env POSTGRES_USER="${POSTGRES_USER:-wodore}" \
            POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-wodore}" "$@"
    fi
}

case "${1:-}" in
start)
    if is_running && router_running; then
        echo "lane-martin: already running at http://localhost:${MARTIN_PORT} (DB: ${DB_NAME}, martin: ${CONTAINER}, router: ${ROUTER})"
        exit 0
    fi
    # Stale exited/created containers with our names would block docker run.
    docker rm -f "$CONTAINER" "$ROUTER" >/dev/null 2>&1 || true
    if [ ! -f martin_sync/config/martin.yaml ]; then
        echo "lane-martin: no martin_sync/config/martin.yaml — run 'scripts/sync-martin.sh' first" >&2
        exit 1
    fi
    if [ ! -f tile_server/tile-router.conf.template ]; then
        echo "lane-martin: no tile_server/tile-router.conf.template" >&2
        exit 1
    fi
    # 1) martin — network-internal only (no host port), like the compose stack
    run_docker env DB_NAME="$DB_NAME" DB_HOST="$DB_HOST" NETWORK="$NETWORK" IMAGE="$IMAGE" \
            CONTAINER="$CONTAINER" \
        bash -c 'docker run -d --rm --name "$CONTAINER" \
            --network "$NETWORK" \
            -e DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${DB_HOST}:5432/${DB_NAME}" \
            -e MARTIN_SYNC_MOUNT=/martin_sync \
            -e TRANSITLAND_API_KEY="${TRANSITLAND_API_KEY:-}" \
            -v "$(pwd)/martin_sync:/martin_sync:ro" \
            "$IMAGE" --config /martin_sync/config/martin.yaml --webui enable-for-all' >/dev/null
    # 2) tile-router — the published single origin (PORT_END), same template
    #    and image as the compose tile-router; mounted as default.conf.template
    #    so it REPLACES the stock config (whose server_name localhost would
    #    otherwise win). /raster/* → the shared dev mapproxy (compose default
    #    network), everything else → lane martin, .mlt → martin + MLT accept.
    docker run -d --rm --name "$ROUTER" \
        --network "$NETWORK" --network "$DEFAULT_NETWORK" \
        -e MARTIN_UPSTREAM="${CONTAINER}:3000" \
        -e MAPPROXY_UPSTREAM="$MAPPROXY_HOST" \
        -v "$(pwd)/tile_server/tile-router.conf.template:/etc/nginx/templates/default.conf.template:ro" \
        -p "${MARTIN_PORT}:80" \
        "$ROUTER_IMAGE" >/dev/null
    # Bounded readiness wait: the router answers on /catalog once martin's
    # DB connection is up.
    for _ in $(seq 1 30); do
        if curl -sf "http://localhost:${MARTIN_PORT}/catalog" >/dev/null; then
            echo "lane-martin: ready at http://localhost:${MARTIN_PORT} (DB: ${DB_NAME}, martin: ${CONTAINER}, router: ${ROUTER})"
            exit 0
        fi
        sleep 1
    done
    echo "lane-martin: containers started but not ready within 30s — check: docker logs ${CONTAINER} / ${ROUTER}" >&2
    exit 1
    ;;
stop)
    docker rm -f "$CONTAINER" "$ROUTER" >/dev/null 2>&1 || true
    echo "lane-martin: stopped (${CONTAINER}, ${ROUTER})"
    ;;
status)
    if is_running && router_running; then
        echo "lane-martin: running — http://localhost:${MARTIN_PORT} (DB: ${DB_NAME}, martin: ${CONTAINER}, router: ${ROUTER})"
    elif is_running; then
        echo "lane-martin: martin up but router ${ROUTER} is NOT — restart with: scripts/lane-martin.sh start (.mlt URLs need the router)" >&2
        exit 1
    else
        echo "lane-martin: not running (start with: scripts/lane-martin.sh start)" >&2
        exit 1
    fi
    ;;
*)
    echo "usage: $0 start|stop|status" >&2
    exit 2
    ;;
esac

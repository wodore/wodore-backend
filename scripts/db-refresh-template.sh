#!/usr/bin/env bash
# Refresh wodore_template — the quiescent snapshot of the dev `wodore`
# database that workz lane databases are cloned from (createdb -T).
#
# Run this whenever a lane needs CURRENT dev data (new migrations applied,
# freshly imported huts, ...). Dump/restore is connection-tolerant, so the
# dev database can stay in use (martin, imagor, app) while this runs.
#
# Takes a few minutes for the ~3.6 GB dev database.
set -euo pipefail

TEMPLATE_DB="${1:-wodore_template}"
SOURCE_DB="${WORKZ_SOURCE_DB:-wodore}"

CID="$(docker ps --format '{{.ID}} {{.Names}}' | grep -i postgis | head -1 | cut -d' ' -f1)"
if [ -z "$CID" ]; then
    echo "db-refresh-template: no postgres container running" >&2
    exit 1
fi

export REFRESH_CID="$CID" REFRESH_TEMPLATE="$TEMPLATE_DB" REFRESH_SOURCE="$SOURCE_DB"

infisical run --env=dev --path /backend --silent --log-level warn -- bash -c '
    set -euo pipefail
    docker_exec() { docker exec -i -e PGPASSWORD="$POSTGRES_PASSWORD" "$REFRESH_CID" "$@"; }
    echo "refreshing $REFRESH_TEMPLATE from $REFRESH_SOURCE (this takes a few minutes)..."
    docker_exec psql -h localhost -U "$POSTGRES_USER" -d postgres \
        -c "DROP DATABASE IF EXISTS $REFRESH_TEMPLATE" \
        -c "CREATE DATABASE $REFRESH_TEMPLATE TEMPLATE template0 OWNER $POSTGRES_USER"
    docker_exec pg_dump -h localhost -U "$POSTGRES_USER" "$REFRESH_SOURCE" \
        | docker_exec psql -h localhost -U "$POSTGRES_USER" -d "$REFRESH_TEMPLATE" -q
    docker_exec psql -h localhost -U "$POSTGRES_USER" -d "$REFRESH_TEMPLATE" -tAc "ANALYZE"
    echo "done: $REFRESH_TEMPLATE is a fresh snapshot of $REFRESH_SOURCE"
'

#!/usr/bin/env bash
# Refresh wodore_template — the quiescent snapshot of the dev `wodore`
# database that workz lane databases are cloned from (createdb -T).
#
# Run this whenever a lane needs CURRENT dev data (new migrations applied,
# freshly imported huts, ...). Dump/restore is connection-tolerant, so the
# dev database can stay in use (martin, imagor, app) while this runs.
#
# Takes a few minutes for the ~3.6 GB dev database.
#
# Targets are env-only (there is deliberately no positional argument —
# `db-refresh-template.sh wodore` must never mean "drop wodore"):
#   WORKZ_TEMPLATE_DB  drop/recreate target  (default: wodore_template)
#   WORKZ_SOURCE_DB    dump source           (default: wodore)
# The live dev DB and system DBs can never be the refresh TARGET.
set -euo pipefail

TEMPLATE_DB="${WORKZ_TEMPLATE_DB:-wodore_template}"
SOURCE_DB="${WORKZ_SOURCE_DB:-wodore}"

if [ "$TEMPLATE_DB" = "$SOURCE_DB" ]; then
    echo "db-refresh-template: refusing: template and source are the same database ('$TEMPLATE_DB')" >&2
    exit 1
fi
for protected in wodore postgres template0 template1; do
    if [ "$TEMPLATE_DB" = "$protected" ]; then
        echo "db-refresh-template: refusing to drop/recreate '$TEMPLATE_DB' (protected: live/system database)" >&2
        exit 1
    fi
    if [ "$SOURCE_DB" = "$protected" ] && [ "$protected" != "wodore" ]; then
        echo "db-refresh-template: refusing '$SOURCE_DB' as source (system database)" >&2
        exit 1
    fi
done

# Resolve the postgres container by its exact name (see AGENTS.md). `|| true`
# keeps a missing container a *checkable* error instead of a silent set -e exit.
CID="$(docker ps --format '{{.ID}} {{.Names}}' | grep -w django-local-postgis | head -1 | cut -d' ' -f1 || true)"
if [ -z "$CID" ]; then
    echo "db-refresh-template: no postgres container running (django-local-postgis)" >&2
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
        | docker_exec psql -h localhost -U "$POSTGRES_USER" -v ON_ERROR_STOP=1 -d "$REFRESH_TEMPLATE" -q
    docker_exec psql -h localhost -U "$POSTGRES_USER" -d "$REFRESH_TEMPLATE" -tAc "ANALYZE"
    echo "done: $REFRESH_TEMPLATE is a fresh snapshot of $REFRESH_SOURCE"
'

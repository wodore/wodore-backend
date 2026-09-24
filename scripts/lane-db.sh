#!/usr/bin/env bash
# Manage the workz lane database on the shared dev postgres
# (docker-local-postgis, port 5432). Called by the .workz.toml hooks with
# WORKZ_DB_NAME set, or manually: scripts/lane-db.sh create|drop [DB_NAME]
#
# Credentials come from Infisical (like every other command in this repo);
# client binaries run inside the postgres container (none on the host).
set -euo pipefail

DB_NAME="${2:-${WORKZ_DB_NAME:-$(sed -n 's/^DB_NAME=//p' .env.local)}}"
TEMPLATE_DB="${WORKZ_TEMPLATE_DB:-wodore_template}"
ACTION="${1:-}"

if [ -z "$DB_NAME" ] || [ -z "$ACTION" ]; then
    echo "usage: $0 create|drop [DB_NAME]" >&2
    exit 2
fi

# Resolve the postgres container (exec-by-name can fail in nested shells).
CID="$(docker ps --format '{{.ID}} {{.Names}}' | grep -i postgis | head -1 | cut -d' ' -f1)"
if [ -z "$CID" ]; then
    echo "lane-db: no postgres container running (start docker-local-postgis first)" >&2
    exit 1
fi

export LANE_DB_ACTION="$ACTION" LANE_DB_NAME="$DB_NAME" LANE_DB_CID="$CID" LANE_DB_TEMPLATE="$TEMPLATE_DB"

infisical run --env=dev --path /backend --silent --log-level warn -- bash -c '
    set -euo pipefail
    psql() { docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" "$LANE_DB_CID" psql -h localhost -U "$POSTGRES_USER" -d postgres -tAc "$1"; }
    exists() { [ "$(psql "SELECT 1 FROM pg_database WHERE datname = '"'"'$LANE_DB_NAME'"'"'")" = "1" ]; }
    case "$LANE_DB_ACTION" in
        create)
            if exists; then
                echo "lane-db: $LANE_DB_NAME already exists — keeping it"
            else
                docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" "$LANE_DB_CID" \
                    createdb -h localhost -U "$POSTGRES_USER" -T "$LANE_DB_TEMPLATE" "$LANE_DB_NAME"
                echo "lane-db: $LANE_DB_NAME created from template $LANE_DB_TEMPLATE"
            fi
            ;;
        drop)
            docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" "$LANE_DB_CID" \
                dropdb -h localhost -U "$POSTGRES_USER" --if-exists "$LANE_DB_NAME"
            echo "lane-db: $LANE_DB_NAME dropped"
            ;;
        *)
            echo "lane-db: unknown action $LANE_DB_ACTION" >&2
            exit 2
            ;;
    esac
'

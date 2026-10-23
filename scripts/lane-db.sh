#!/usr/bin/env bash
# Manage the workz lane database on the shared dev postgres
# (django-local-postgis, port 5432). Called by the .workz.toml hooks or
# manually: scripts/lane-db.sh create|drop [DB_NAME]
#
# The lane DB name comes from the workz-managed `.env.local` (DB_NAME);
# workz does not export it to hooks as an env var. Credentials come from
# Infisical (like every other command in this repo); client binaries run
# inside the postgres container (none on the host).
set -euo pipefail

DB_NAME="${2:-$(sed -n 's/^DB_NAME=//p' .env.local)}"
TEMPLATE_DB="${WORKZ_TEMPLATE_DB:-wodore_template}"
ACTION="${1:-}"

if [ -z "$DB_NAME" ] || [ -z "$ACTION" ]; then
    echo "usage: $0 create|drop [DB_NAME]" >&2
    exit 2
fi

# `drop` refuses anything that is not lane-named: only workz-allocated lane
# databases may be dropped — never the live dev DB, the template snapshot
# or system databases. Lane-named means: pi_* / *lane* patterns, or any
# name the workz-managed `.env.local` in THIS worktree declares as its own
# (workz derives branch-based names like `feat_tmb_huts` that match no
# pattern — the .env.local entry is the authoritative allocation record).
if [ "$ACTION" = "drop" ]; then
    case "$DB_NAME" in
        wodore|wodore_template|postgres|template0|template1)
            echo "lane-db: refusing to drop '$DB_NAME' (protected database)" >&2
            exit 1
            ;;
    esac
    managed_db="$(sed -n 's/^DB_NAME=//p' .env.local 2>/dev/null || true)"
    if ! printf '%s' "$DB_NAME" | grep -Eq '^pi_|lane' && [ "$DB_NAME" != "$managed_db" ]; then
        echo "lane-db: refusing to drop '$DB_NAME' (not a lane database; expected pi_*, *lane* or this worktree's .env.local DB_NAME)" >&2
        exit 1
    fi
fi

# Resolve the postgres container by its exact name (see AGENTS.md);
# exec-by-name can fail in nested shells, hence ID + exec. `|| true` keeps
# a missing container a *checkable* error instead of a silent set -e exit.
CID="$(docker ps --format '{{.ID}} {{.Names}}' | grep -w django-local-postgis | head -1 | cut -d' ' -f1 || true)"
if [ -z "$CID" ]; then
    echo "lane-db: no postgres container running (start django-local-postgis first)" >&2
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
            # --force: also terminate lingering lane connections (a devserver
            # left running would otherwise fail the drop and orphan the DB).
            docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" "$LANE_DB_CID" \
                dropdb -h localhost -U "$POSTGRES_USER" --if-exists --force "$LANE_DB_NAME"
            echo "lane-db: $LANE_DB_NAME dropped"
            ;;
        *)
            echo "lane-db: unknown action $LANE_DB_ACTION" >&2
            exit 2
            ;;
    esac
'

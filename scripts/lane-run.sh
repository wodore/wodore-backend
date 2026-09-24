#!/usr/bin/env bash
# Run a command in this worktree against the LANE database.
#
#   scripts/lane-run.sh .venv/bin/pytest
#   scripts/lane-run.sh .venv/bin/python manage.py migrate
#
# Why this exists: workz writes the lane DB name into .env.local (DB_NAME),
# but Django settings read POSTGRES_DB via python-decouple (os.environ first,
# then config/.env*) and every real command runs through `infisical run`,
# which injects POSTGRES_DB from Infisical — the .env.local value would be
# shadowed. This wrapper re-injects the lane DB name AFTER infisical, so the
# inner `env` assignment wins. See AGENTS.md § Worktrees / workz.
set -euo pipefail

if [ ! -f .env.local ]; then
    echo "lane-run: no .env.local here — run 'workz sync . --isolated' first (or: not a workz worktree)" >&2
    exit 1
fi

DB_NAME="$(sed -n 's/^DB_NAME=//p' .env.local)"
if [ -z "$DB_NAME" ]; then
    echo "lane-run: no DB_NAME in .env.local (workz managed block missing?)" >&2
    exit 1
fi

# Point the backend at the lane martin (scripts/lane-martin.sh, port
# PORT_END — PORT+1 is taken by workz's REDIS_URL allocation) when this is
# an isolated lane. Overridable; without a PORT range (not isolated)
# nothing is injected and the settings default (shared martin :8075) applies.
PORT_END="$(sed -n 's/^PORT_END=//p' .env.local)"
EXTRA_ENV=("POSTGRES_DB=$DB_NAME")
if [ -n "$PORT_END" ]; then
    EXTRA_ENV+=("MARTIN_TILE_URL=${MARTIN_TILE_URL:-http://localhost:$PORT_END}")
fi

export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-server.settings}"
# NOTE: no --silent on the infisical invocation — it swallows the CHILD's
# stdout too, so interactive commands (createsuperuser) hang with invisible
# prompts. --log-level warn keeps infisical's own logging quiet.
exec infisical run --env=dev --path /backend --log-level warn \
    -- env "${EXTRA_ENV[@]}" "$@"

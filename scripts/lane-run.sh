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

export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-server.settings}"
exec infisical run --env=dev --path /backend --silent --log-level warn \
    -- env POSTGRES_DB="$DB_NAME" "$@"

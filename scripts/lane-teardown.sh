#!/usr/bin/env bash
# Idempotent lane teardown — the single cleanup entry shared by every host:
#
#   workz done   → .workz.toml [hooks] pre_done (before worktree removal)
#   paseo        → paseo.json worktree.teardown (workspace archive)
#   manual       → anytime; safe to re-run
#
# Order matters: stop the dev server first (it holds lane DB connections),
# then reap anything else still bound to the lane's ports, then the lane
# martin container (workz reap cannot remove containers), then drop the
# lane database (dropdb --force also terminates lingering connections as a
# final safety net).
set -euo pipefail
cd "$(dirname "$0")/.."

# Not a workz lane (no managed block)? Nothing to clean — exit clean.
if ! grep -q '^PORT=' .env.local 2>/dev/null; then
    echo "lane-teardown: no workz managed block in .env.local — nothing to clean up"
    exit 0
fi

scripts/lane-dev.sh stop >/dev/null 2>&1 || true
workz reap -y >/dev/null 2>&1 || true
scripts/lane-martin.sh stop
scripts/lane-db.sh drop

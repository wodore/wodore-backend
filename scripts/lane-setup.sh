#!/usr/bin/env bash
# Idempotent lane provisioning — the single setup entry shared by every host:
#
#   workz start  → .workz.toml [hooks] post_start
#   paseo        → paseo.json worktree.setup (after `workz sync --isolated`)
#   pi agent     → lane step 1 (the global pi hook runs `workz sync
#                  --isolated`, which fires NO hooks)
#
# workz sync has already copied .env*/.infisical.json and allocated the port
# range + DB name (managed block in .env.local). This script creates what
# sync cannot: the lane venv, the lane database and the martin_sync copy.
# All steps are idempotent — re-running after a crash is safe.
set -euo pipefail
cd "$(dirname "$0")/.."

scripts/lane-venv.sh
scripts/lane-db.sh create
scripts/sync-martin.sh

echo "lane-setup: ready — dev server: scripts/lane-dev.sh fg|start (port $(sed -n 's/^PORT=//p' .env.local 2>/dev/null || true))"

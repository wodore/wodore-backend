#!/usr/bin/env bash
# Provision this lane's own venv (never symlinked, see .workz.toml):
#
# 1. uv sync --frozen --extra private — hardlinked from the shared uv cache
#    (~6 MB marginal disk, sub-second warm). --extra private is required:
#    plain `uv sync` silently omits hut-services-private and the booking
#    services vanish from settings.SERVICES.
# 2. Patch .venv/bin/activate with a LANE-AWARE `app` shell function.
#
#    The main checkout's function (inv update-venv --infisical) is
#    `app() { inv app.app -i --cmd "$*"; }` — infisical + the venv's `app`
#    console script. Injecting that into a lane would wrap infisical too,
#    but infisical injects the DEV database (POSTGRES_DB=wodore) — .env.local
#    is not in Django's env chain (that's why lane-run.sh exists). A lane
#    must route through lane-run.sh so `app <cmd>` hits the LANE database:
#    app() { scripts/lane-run.sh .venv/bin/python manage.py "$@"; }
#
# No `make init` needed for lanes: pre-commit hooks live in the shared
# .git/hooks (worktrees run them automatically) and the .volumes/pgdata +
# media/imagor_data directories are only needed for local compose/imagor
# work (main checkout).
set -euo pipefail

uv sync --frozen --extra private

ACTIVATE=".venv/bin/activate"
if [ ! -f "$ACTIVATE" ]; then
    echo "lane-venv: $ACTIVATE not found — did uv sync run here?" >&2
    exit 1
fi
if ! grep -q "# LANE app function" "$ACTIVATE"; then
    cat >> "$ACTIVATE" <<'EOF'

# LANE app function (lane-aware: manage.py against the LANE database).
# Default mode routes through scripts/lane-run.sh (infisical), mirroring
# the main checkout's `inv update-venv --infisical` function (inf() { inv
# app.app -i --cmd "$*"; }). Local-env mode — like `inv app.app` WITHOUT
# -i, where the original task runs the bare console script on your shell
# environment — is enabled with WODORE_APP_NO_INFISICAL=1: everything
# except POSTGRES_DB/MARTIN_TILE_URL (taken from .env.local so you still
# hit the LANE database) must come from your own environment.
app() {
    if [ "${WODORE_APP_NO_INFISICAL:-0}" = "1" ]; then
        POSTGRES_DB="$(sed -n 's/^DB_NAME=//p' .env.local 2>/dev/null)" \
        MARTIN_TILE_URL="${MARTIN_TILE_URL:-http://localhost:$(sed -n 's/^PORT_END=//p' .env.local 2>/dev/null)}" \
        .venv/bin/python manage.py "$@"
    else
        scripts/lane-run.sh .venv/bin/python manage.py "$@"
    fi
}
# LANE app function end
EOF
fi

echo "lane-venv: venv ready — source .venv/bin/activate for the lane-aware app()"

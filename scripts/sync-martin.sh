#!/usr/bin/env bash
# Copy the generated martin_sync/ dir (config, sprites, mbtiles state,
# ~109 MB) from the MAIN checkout into this worktree. It is gitignored, so
# git won't bring it, and workz `copy_add` only handles regular files
# (verified against the workz binary — no directory copies), so this hook
# script does it instead.
#
# Every lane gets its OWN copy: refill it against the lane DB with
#   scripts/lane-run.sh .venv/bin/python manage.py martin_sync
# and a lane-scoped martin can mount it without touching other lanes.
set -euo pipefail

if [ -d martin_sync ]; then
    echo "martin-sync: martin_sync/ already present — keeping it" >&2
    exit 0
fi

MAIN_CHECKOUT="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"
if [ ! -d "$MAIN_CHECKOUT/martin_sync" ]; then
    echo "martin-sync: no martin_sync/ in the main checkout ($MAIN_CHECKOUT) —" \
        "run 'app martin_sync' there first" >&2
    exit 1
fi

cp -r "$MAIN_CHECKOUT/martin_sync" .
echo "martin-sync: copied martin_sync/ from $MAIN_CHECKOUT" >&2
echo "martin-sync: refill per lane: scripts/lane-run.sh .venv/bin/python manage.py martin_sync" >&2

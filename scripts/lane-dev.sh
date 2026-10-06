#!/usr/bin/env bash
# Start/stop this lane's Django dev server on the workz-allocated port.
#
#   scripts/lane-dev.sh fg      # guarded foreground (paseo service, workz run)
#   scripts/lane-dev.sh start   # detached via workz run (logs: lane-dev.sh logs)
#   scripts/lane-dev.sh stop    # workz run --stop (SIGTERM, then --force)
#   scripts/lane-dev.sh status  # port listening? ours? URL?
#
# The port comes from the workz-managed block in .env.local — workz is the
# ONLY port allocator for lanes. A paseo-allocated $PASEO_PORT would be
# invisible to workz run/reap/preview/done, so paseo.json's `api` service
# wraps `fg` instead of using its own port.
#
# `fg` guards double starts: a listener already on the port that belongs to
# THIS worktree is a friendly no-op (exit 0 — supervised services may
# restart into a lane whose server is still up); a foreign listener is a
# hard error.
set -euo pipefail

usage() { echo "usage: $0 fg|start|stop|status|logs" >&2; exit 2; }

COMMAND="${1:-}"
case "$COMMAND" in fg|start|stop|status|logs) ;; *) usage ;; esac
cd "$(dirname "$0")/.."

if [ ! -f .env.local ]; then
    echo "lane-dev: no .env.local — run 'workz sync . --isolated' first (or: not a workz lane)" >&2
    exit 1
fi
PORT="$(sed -n 's/^PORT=//p' .env.local)"
if [ -z "$PORT" ]; then
    echo "lane-dev: no PORT in .env.local (workz managed block missing?)" >&2
    exit 1
fi
WORKTREE_ROOT="$(pwd -P)"

listener_pids() { lsof -t -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true; }

# Is a listener one of ours? Compare the listening process's cwd with this
# worktree root (dev servers inherit the shell's cwd; /proc/<pid>/cwd is
# readable for own processes — the common lane case).
ours_listening() {
    for pid in $(listener_pids); do
        [ "$(readlink "/proc/$pid/cwd" 2>/dev/null || true)" = "$WORKTREE_ROOT" ] && return 0
    done
    return 1
}

case "$COMMAND" in
fg)
    PIDS="$(listener_pids)"
    if [ -n "$PIDS" ]; then
        if ours_listening; then
            echo "lane-dev: already running at http://localhost:$PORT — nothing to do"
            exit 0
        fi
        echo "lane-dev: port :$PORT held by a foreign process (pid $(echo "$PIDS" | tr '\n' ' '))— refusing to start" >&2
        exit 1
    fi
    exec scripts/lane-run.sh .venv/bin/python manage.py runserver "$PORT"
    ;;
start)
    exec workz run
    ;;
stop)
    exec workz run --stop
    ;;
logs)
    exec workz run --logs
    ;;
status)
    PIDS="$(listener_pids)"
    if [ -z "$PIDS" ]; then
        echo "lane-dev: down (nothing listening on :$PORT)"
        exit 1
    elif ours_listening; then
        echo "lane-dev: up at http://localhost:$PORT"
    else
        echo "lane-dev: port :$PORT held by a FOREIGN process (pid $(echo "$PIDS" | tr '\n' ' '))" >&2
        exit 1
    fi
    ;;
esac

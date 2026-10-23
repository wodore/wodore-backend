#!/usr/bin/env bash
# Start/stop this lane's Django dev server on the workz-allocated port.
#
#   scripts/lane-dev.sh fg      # guarded foreground supervisor: runserver
#                               # + qcluster (see below) — used by the paseo
#                               # 'runserver' service and by `workz run`
#   scripts/lane-dev.sh start   # detached via workz run (logs: lane-dev.sh logs)
#   scripts/lane-dev.sh stop    # workz run --stop (SIGTERM, then --force)
#   scripts/lane-dev.sh status  # port listening? ours? URL? qcluster up?
#   scripts/lane-dev.sh attach  # print recent runserver output: the paseo
#                               # service terminal via `paseo terminal capture`,
#                               # else the last detached (workz) run log
#   scripts/lane-dev.sh kill    # hard-stop runserver + qcluster
#   scripts/lane-dev.sh logs    # workz run --logs (last DETACHED run only)
#
# The port comes from the workz-managed block in .env.local — workz is the
# ONLY port allocator for lanes. A paseo-allocated $PASEO_PORT would be
# invisible to workz run/reap/preview/done, so paseo.json's `runserver`
# service
# wraps `fg` instead of using its own port.
#
# `fg` guards double starts: a listener already on the port that belongs to
# THIS worktree is a friendly no-op (exit 0 — supervised services may
# restart into a lane whose server is still up); a foreign listener is a
# hard error.
#
# qcluster (django-q2): `fg` starts `manage.py qcluster` next to runserver
# and kills it again whenever runserver stops — via traps on the wrapper,
# so it works for paseo `script stop`, `workz run --stop`, Ctrl-C and
# crashes alike. Disable it per lane with `QCLUSTER=0` in .env.local
# (outside the workz managed block — same pattern as FRONTEND_DOMAIN) or
# one-off with `QCLUSTER=0 scripts/lane-dev.sh fg`.
#
# Process management is cwd-scoped discovery (pgrep over `manage.py
# qcluster|runserver` + /proc/<pid>/cwd == this worktree), not pidfiles:
# it survives SIGKILLed wrappers, covers the infisical wrapper and the
# qcluster worker forks, and can't leak a stale state file. django-q2's
# qcluster HANGS on SIGTERM in this stack (graceful shutdown never
# finishes), so every stop is TERM → bounded wait → SIGKILL.
set -euo pipefail

usage() { echo "usage: $0 fg|start|stop|status|attach|kill|logs" >&2; exit 2; }

COMMAND="${1:-}"
case "$COMMAND" in fg|start|stop|status|attach|kill|logs) ;; *) usage ;; esac
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
        if [ "$(readlink "/proc/$pid/cwd" 2>/dev/null || true)" = "$WORKTREE_ROOT" ]; then
            return 0
        fi
    done
    return 1
}

# This worktree's dev-server process tree: the `.venv/bin/python manage.py
# ...` processes (qcluster's forked workers share the cmdline) plus the
# `infisical run -- ... .venv/bin/python manage.py ...` wrappers around
# them. The interpreter prefix in the pattern is what keeps grep/agent
# shells that merely MENTION manage.py from matching. Empty when nothing
# runs.
lane_server_pids() {
    local pid kind="${1:-}"
    for pid in $(pgrep -f '\.?venv/bin/python3? manage\.py (qcluster|runserver)' 2>/dev/null || true); do
        if [ "$pid" = "$$" ] || [ "$pid" = "$PPID" ]; then continue; fi
        if [ "$(readlink "/proc/$pid/cwd" 2>/dev/null || true)" = "$WORKTREE_ROOT" ]; then
            if [ -z "$kind" ] || tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | grep -q "manage\.py $kind"; then
                echo "$pid"
            fi
        fi
    done
    return 0
}

qcluster_pids() { lane_server_pids qcluster; }

# TERM the given pids, wait up to ~5 s for the whole set to disappear, then
# SIGKILL the leftovers (qcluster ignores a plain TERM forever).
# NOTE: no `[ cond ] && cmd` shortcuts — with `set -e` a false condition IS
# the list's final command and would abort the script.
stop_pids() {
    local pids pid left
    pids="$1"
    [ -n "$pids" ] || return 0
    kill $pids 2>/dev/null || true
    left="$pids"
    for _ in $(seq 1 10); do
        left=""
        for pid in $pids; do
            if [ -d "/proc/$pid" ]; then left="$left $pid"; fi
        done
        if [ -z "$left" ]; then return 0; fi
        sleep 0.5
    done
    for pid in $left; do
        kill -9 "$pid" 2>/dev/null || true
    done
    return 0
}

# Stop ALL of this lane's dev-server processes (runserver + qcluster).
stop_lane_servers() {
    local pids
    pids="$(lane_server_pids)"
    stop_pids "$pids"
    # late forks (qcluster workers respawning during shutdown)
    pids="$(lane_server_pids)"
    if [ -n "$pids" ]; then
        kill -9 $pids 2>/dev/null || true
    fi
    return 0
}

want_qcluster() {
    local val="${QCLUSTER:-$(sed -n 's/^QCLUSTER=//p' .env.local)}"
    val="${val:-1}"
    case "$(echo "$val" | tr '[:upper:]' '[:lower:]')" in
        0|false|no|off) return 1 ;;
        *) return 0 ;;
    esac
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
    # A previous run killed with SIGKILL (workz --force, OOM) can leave its
    # qcluster orphaned — retire it before starting a fresh one. (The
    # friendly no-op branch above deliberately never touches processes: they
    # belong to the still-running session.)
    if [ -n "$(lane_server_pids)" ]; then
        echo "lane-dev: retiring stale dev-server processes (pid $(lane_server_pids | tr '\n' ' '))"
        stop_lane_servers
    fi

    RPID=""
    QPID=""
    cleanup() {
        trap - EXIT INT TERM
        stop_lane_servers
        wait 2>/dev/null || true
    }
    trap cleanup EXIT
    # Background children are what make this safe: bash runs signal traps
    # immediately (nothing is blocking in the foreground), so a lone
    # SIGTERM to the wrapper — even one that spares the process group —
    # still tears runserver and qcluster down.
    trap 'exit 143' TERM
    trap 'exit 130' INT

    if want_qcluster; then
        scripts/lane-run.sh .venv/bin/python manage.py qcluster &
        QPID=$!
        echo "lane-dev: qcluster starting (pid $QPID — disable with QCLUSTER=0)"
    else
        echo "lane-dev: qcluster disabled (QCLUSTER=$(printf %s "${QCLUSTER:-$(sed -n 's/^QCLUSTER=//p' .env.local)}" | tr -d '\n'))"
    fi

    scripts/lane-run.sh .venv/bin/python manage.py runserver "$PORT" &
    RPID=$!
    wait "$RPID"
    ;;
start)
    exec workz run
    ;;
stop)
    exec workz run --stop
    ;;
attach)
    LINES="${2:-200}"
    TID=""
    if command -v paseo >/dev/null 2>&1; then
        TID="$(paseo script ls --json --cwd "$PWD" 2>/dev/null \
            | jq -r '(.[] | select(.scriptName == "runserver") | .terminalId) // empty' 2>/dev/null || true)"
        TID="${TID%%$'\n'*}"
    fi
    if [ -n "$TID" ]; then
        echo "lane-dev: runserver output — paseo terminal $TID, last $LINES lines (live view: open the runserver terminal in the Paseo app)"
        paseo terminal capture "$TID" --scrollback | tail -n "$LINES"
    elif ours_listening; then
        echo "lane-dev: runserver is up on :$PORT but running unsupervised (bare terminal?) — no readable output" >&2
        exit 1
    else
        echo "lane-dev: runserver down — last detached (workz) run log:"
        exec workz run --logs
    fi
    ;;
kill)
    PIDS="$(listener_pids)"
    if [ -n "$PIDS" ]; then
        if ! ours_listening; then
            echo "lane-dev: port :$PORT held by a FOREIGN process (pid $(echo "$PIDS" | tr '\n' ' '))— refusing to kill" >&2
            exit 1
        fi
        echo "lane-dev: stopping runserver (pid $(echo "$PIDS" | tr '\n' ' ')) on :$PORT"
        stop_pids "$PIDS"
    else
        echo "lane-dev: runserver not listening on :$PORT"
    fi
    if [ -n "$(qcluster_pids)" ]; then
        echo "lane-dev: stopping qcluster (pid $(qcluster_pids | tr '\n' ' '))"
        stop_pids "$(qcluster_pids)"
    else
        echo "lane-dev: qcluster not running"
    fi
    # sweep anything left of this lane's dev-server tree
    if [ -n "$(lane_server_pids)" ]; then
        echo "lane-dev: sweeping leftovers (pid $(lane_server_pids | tr '\n' ' '))"
        stop_lane_servers
    fi
    ;;
logs)
    exec workz run --logs
    ;;
status)
    PIDS="$(listener_pids)"
    if [ -z "$PIDS" ]; then
        echo "lane-dev: down (nothing listening on :$PORT)"
    elif ours_listening; then
        echo "lane-dev: up at http://localhost:$PORT"
    else
        echo "lane-dev: port :$PORT held by a FOREIGN process (pid $(echo "$PIDS" | tr '\n' ' '))" >&2
    fi
    if [ -n "$(qcluster_pids)" ]; then
        echo "lane-dev: qcluster up (pid $(qcluster_pids | tr '\n' ' '))"
    else
        echo "lane-dev: qcluster down"
    fi
    [ -n "$PIDS" ] && ours_listening
    ;;
esac

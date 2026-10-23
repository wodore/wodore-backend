#!/usr/bin/env bash

set -o errexit
set -o nounset
set -o pipefail

# Load build timestamp if available
if [ -f /code/.build_timestamp ]; then
  # shellcheck disable=SC1091
  source /code/.build_timestamp
fi

: "${DJANGO_DATABASE_HOST:=db}"
: "${DJANGO_DATABASE_PORT:=5432}"

# Wait for Postgres unless the caller opted out (k8s sets WAIT_FOR_DB=0:
# readiness is owned by probes and the migrate-check init container has
# already gated database access — no hard boot dependency wanted).
if [ "${WAIT_FOR_DB:-1}" != "0" ]; then
  echo "Waiting for Postgres ${DJANGO_DATABASE_HOST}:${DJANGO_DATABASE_PORT} to be ready..."
  # We need this line to make sure that this container is started
  # after the one with postgres:
  wait-for-it \
    --host="$DJANGO_DATABASE_HOST" \
    --port="$DJANGO_DATABASE_PORT" \
    --timeout=90 \
    --strict

  # It is also possible to wait for other services as well: redis, elastic, mongo
  echo "Postgres ${DJANGO_DATABASE_HOST}:${DJANGO_DATABASE_PORT} is up"
fi

# Gunicorn 25.x opens a control socket (.gunicorn/ in cwd) by default; it is
# unused in containers and fails on root-owned cwd. Disable unless the caller
# opted in via GUNICORN_CMD_ARGS.
export GUNICORN_CMD_ARGS="${GUNICORN_CMD_ARGS:+$GUNICORN_CMD_ARGS }--no-control-socket"

# Evaluating the passed command (exec-form safe: argument boundaries are
# preserved, unlike the previous `exec $cmd` word-splitting):
exec "$@"

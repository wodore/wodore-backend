#!/usr/bin/env bash

set -o errexit
set -o nounset
set -o pipefail

readonly cmd="$*"

# Load build timestamp if available
if [ -f /code/.build_timestamp ]; then
  # shellcheck disable=SC1091
  source /code/.build_timestamp
fi

: "${DJANGO_DATABASE_HOST:=db}"
: "${DJANGO_DATABASE_PORT:=5432}"

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


# Evaluating passed command (do not touch):
# shellcheck disable=SC2086
exec $cmd

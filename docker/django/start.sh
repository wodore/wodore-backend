#!/usr/bin/env bash

set -o errexit
set -o nounset
set -o pipefail

# Generic application-server start script (renamed from `gunicorn.sh`: the
# server is selected in `gunicorn_config.py` — WSGI/ASGI via ASGI_ENABLED —
# and could be swapped entirely without touching the entrypoint chain,
# the Dockerfiles, or the k8s manifests that reference this script).
#
# Flags (env equivalents in brackets, flags win):
#   --no-migrate      skip `manage.py migrate` on boot
#                     [MIGRATE_ON_START=0] — k8s sets this: migrations run as
#                     a dedicated Job and a migration check gates pod startup,
#                     so N pods racing DDL locks at every rollout is unwanted.
#   --port 8008       bind port, full form via env
#                     [GUNICORN_BIND=HOST:PORT, default 0.0.0.0:8000 from
#                     gunicorn_config.py] — k8s serves on 8008.
#
# Env-only knobs (also read by `gunicorn_config.py` directly):
#   GUNICORN_WORKERS  worker count (default cpu*2+1)
#   GUNICORN_CMD_ARGS extra gunicorn flags, e.g. "--timeout 120";
#                     `--no-control-socket` is appended by entrypoint.sh
#   ASGI_ENABLED=1    uvicorn workers on server.asgi (see gunicorn_config.py)
#
# Note: `compilemessages` is NOT run (neither here nor in the image build):
# locale/ is currently empty, there is nothing to compile.

# Check that $DJANGO_ENV is a serve-safe environment. Wodore serves from
# two: "production" and "staging" (server/settings/environments/); the
# wemake-template default of rejecting anything but "production" would
# crash-loop the k8s staging namespace, which sets DJANGO_ENV=staging.
echo "DJANGO_ENV is ${DJANGO_ENV:-<unset>}"
case "${DJANGO_ENV:-}" in
  production | staging)
    ;;
  *)
    echo 'Error: DJANGO_ENV is not set to "production" or "staging".'
    echo 'Application will not start.'
    exit 1
    ;;
esac

export DJANGO_ENV

migrate=1
if [ "${MIGRATE_ON_START:-1}" = "0" ]; then
  migrate=0
fi

while [ $# -gt 0 ]; do
  case "$1" in
    --no-migrate)
      migrate=0
      ;;
    --port)
      if [ $# -lt 2 ]; then
        echo 'Error: --port requires a value' >&2
        exit 1
      fi
      export GUNICORN_BIND="0.0.0.0:$2"
      shift
      ;;
    --port=*)
      export GUNICORN_BIND="0.0.0.0:${1#*=}"
      ;;
    *)
      echo "Error: unknown option: $1" >&2
      exit 1
      ;;
  esac
  shift
done

# Run python specific scripts:
# Running migrations in startup script might not be the best option, see:
# docs/pages/template/production-checklist.rst
# (docker-compose single-container flow keeps it enabled; k8s disables it)
if [ "$migrate" = "1" ]; then
  python /code/manage.py migrate --noinput
fi

# Start the app server (gunicorn; WSGI default, uvicorn ASGI when
# ASGI_ENABLED=1 — the app module and worker class live in the config):
# Docs: https://gunicorn.org/en/stable/settings.html
# Make sure it is in sync with `docker/django/ci.sh` check.
exec /usr/local/bin/gunicorn \
  --config python:docker.django.gunicorn_config

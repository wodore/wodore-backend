# Gunicorn configuration file
# https://gunicorn.org/en/stable/configure.html#configuration-file
# https://gunicorn.org/en/stable/settings.html

import multiprocessing
import os

bind = "0.0.0.0:8000"
# Concerning `workers` setting see:
# https://github.com/wemake-services/wemake-django-template/issues/1022
workers = multiprocessing.cpu_count() * 2 + 1
# Override via env (parity with the k8s deployment, which passes
# GUNICORN_WORKERS explicitly): applies to both runtimes; for ASGI
# prefer fewer, fatter workers (see the switch notes below).
_workers_env = os.environ.get("GUNICORN_WORKERS", "").strip()
if _workers_env:
    workers = int(_workers_env)

max_requests = 2000
max_requests_jitter = 400

log_file = "-"
chdir = "/code"
worker_tmp_dir = "/dev/shm"

# Async-ready runtime switch (openspec: async-api-staging).
#
# Default (unset/0): sync WSGI workers on server.wsgi — exactly the
# previous behavior. ASGI_ENABLED=1: uvicorn workers on server.asgi —
# one event loop per worker; async views get real cross-request
# concurrency, sync views run auto-adapted in bridged threads.
#
# For ASGI also set POSTGRES_POOL=1 (psycopg3 pool instead of
# CONN_MAX_AGE, see settings/components/common.py) and prefer fewer,
# fatter workers (e.g. GUNICORN_WORKERS=3) with a per-worker pool cap
# (POSTGRES_POOL_SIZE, default 10) — pool size x workers is the DB
# connection budget.
#
# Measured guidance (openspec PoC, lane): ASGI x3 workers = ~3.5x
# sustained throughput of sync WSGI x3 on geo endpoints and survives
# slow clients and long requests (sync workers are killed by
# --timeout on both).
ASGI_ENABLED = os.environ.get("ASGI_ENABLED", "").lower() in {"1", "true", "yes"}

if ASGI_ENABLED:
    worker_class = "uvicorn_worker.UvicornWorker"
    wsgi_app = "server.asgi:application"
else:
    wsgi_app = "server.wsgi:application"

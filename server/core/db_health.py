"""Database health checks with psycopg-pool diagnostics.

The deep ``/health/`` endpoint (humans, debugging) needs a pooled
connection. During the 2026-10-05 staging wedge it failed for 12 minutes
straight with psycopg_pool's ``couldn't get a connection after 30.00 sec``
while nothing in the logs could distinguish a connection leak (pool slots
never returned) from slow churn — the pool's own stats
(``ConnectionPool.get_stats()``) would have. ``PoolStatsDatabaseCheck``
logs them on every DB check failure.

``FastDatabaseReadinessCheck`` backs ``/health/ready/`` for k8s readiness:
it caps the DB touch at a small wall-clock budget, so an exhausted pool
answers a fast, clean 503 instead of hanging until the kubelet probe times
out (probe timeout 15s < pool wait 30s meant the pod only ever reported
``context deadline exceeded`` during the wedge, and every probe left a
zombie health check running for its full pool wait).
"""

import dataclasses
import logging
import threading

from health_check.contrib.db_heartbeat.backends import DatabaseHeartBeatCheck
from health_check.exceptions import ServiceUnavailable

from django.db import connections

logger = logging.getLogger(__name__)


class PoolStatsDatabaseCheck(DatabaseHeartBeatCheck):
    """``DatabaseHeartBeatCheck`` that logs psycopg pool stats on failure.

    No-op (and no extra output) when pooling is not enabled
    (``POSTGRES_POOL`` unset — ``connections[alias].pool`` is ``None``).
    """

    def check_status(self):
        try:
            super().check_status()
        except BaseException:
            self._log_pool_stats()
            raise

    def _log_pool_stats(self) -> None:
        try:
            # None unless the psycopg3 pool is configured (POSTGRES_POOL=1).
            pool = connections[self.alias].pool
        except Exception:  # pragma: no cover - never mask the check result
            return
        if pool is None:
            return
        try:
            logger.error(
                "psycopg pool stats at DB health-check failure (%s): %s",
                self.alias,
                pool.get_stats(),
            )
        except Exception:  # pragma: no cover - never mask the check result
            pass


@dataclasses.dataclass
class FastDatabaseReadinessCheck(DatabaseHeartBeatCheck):
    """DB readiness under a hard wall-clock budget (``/health/ready/``).

    With the psycopg pool configured it performs exactly the operation
    that starves — a ``pool.getconn(timeout=budget_seconds)`` checkout —
    and runs ``SELECT 1`` on the connection. Without a pool (WSGI /
    ``CONN_MAX_AGE`` setups) it bounds the plain heartbeat query with a
    helper thread.

    Probe this with a timeout of ~3x ``budget_seconds`` so the endpoint's
    own 503 (with a reason) wins the race against the kubelet deadline.
    """

    budget_seconds: float = 2.0

    def check_status(self):
        pool = self._pool_or_none()
        if pool is not None:
            self._check_via_pool(pool)
            return
        self._check_via_thread()

    def _pool_or_none(self):
        try:
            return connections[self.alias].pool
        except Exception:  # pragma: no cover - fall back to the heartbeat
            return None

    def _check_via_pool(self, pool) -> None:
        # Django creates the pool with open=False and opens it lazily before
        # its first getconn (backends/postgresql: "If nothing else has opened
        # the pool, open it now"). A freshly booted worker whose first
        # traffic is a readiness probe would otherwise fail with "the pool
        # ... is not open yet" — so open it exactly like Django does (the
        # call is idempotent for an already-open pool).
        try:
            pool.open()
        except Exception as exc:
            raise ServiceUnavailable(f"database pool failed to open: {exc}")
        try:
            conn = pool.getconn(timeout=self.budget_seconds)
        except Exception as exc:
            raise ServiceUnavailable(
                f"database pool checkout exceeded {self.budget_seconds}s: {exc}"
            )
        try:
            row = conn.execute("SELECT 1").fetchone()
        except Exception as exc:
            raise ServiceUnavailable(f"readiness query failed: {exc}")
        finally:
            pool.putconn(conn)
        if row != (1,):  # pragma: no cover - defensive
            raise ServiceUnavailable("readiness query returned an unexpected result")

    def _check_via_thread(self) -> None:
        outcome: dict = {}

        def _heartbeat() -> None:
            try:
                DatabaseHeartBeatCheck.check_status(self)
            except BaseException as exc:
                outcome["exc"] = exc
            else:
                outcome["ok"] = True

        worker = threading.Thread(target=_heartbeat, daemon=True)
        worker.start()
        worker.join(self.budget_seconds)
        if worker.is_alive():
            # The daemon worker stays parked on its (bounded) query; the
            # check itself must not hold the probe hostage.
            raise ServiceUnavailable(
                f"database not answering within {self.budget_seconds}s"
            )
        if "ok" not in outcome:
            raise outcome["exc"]

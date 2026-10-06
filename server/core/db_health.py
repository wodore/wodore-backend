"""Database health-check with psycopg-pool diagnostics.

The deep ``/health/`` endpoint (k8s readiness) needs a pooled connection.
During the 2026-10-05 staging wedge it failed for 12 minutes straight with
psycopg_pool's ``couldn't get a connection after 30.00 sec`` while nothing
in the logs could distinguish a connection leak (pool slots never returned)
from slow churn — the pool's own stats (``ConnectionPool.get_stats()``)
would have. This check logs them on every DB check failure.
"""

import logging

from health_check.contrib.db_heartbeat.backends import DatabaseHeartBeatCheck

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

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

Issue #333 follow-up: k8s probes this endpoint every few seconds, so the
check doubles as a **pool saturation sampler** — every probe samples
``get_stats()`` and warns (rate-limited) while requests are still being
served but the pool is fully checked out or queueing; a failed checkout
logs the full stats at ERROR, capturing exactly the evidence both wedge
incidents lacked.
"""

import dataclasses
import logging
import threading
import time
from typing import Any, override

from health_check.contrib.db_heartbeat.backends import DatabaseHeartBeatCheck
from health_check.exceptions import ServiceUnavailable

from django.db import connections

logger = logging.getLogger(__name__)

#: Seconds between saturation warnings per alias (probes run every few
#: seconds; without the limit a wedged pool would spam one line per probe).
SATURATION_LOG_INTERVAL = 60.0


class PoolSaturationSampler:
    """Rate-limited psycopg-pool saturation sampling (issue #333).

    Called from the readiness check on every k8s probe. Two signals:

    * ``pool_available == 0`` while the pool has connections — every slot
      is checked out; the next slow holder tips into checkout timeouts.
    * a rising ``requests_queued`` counter — some client had to wait for
      a slot between probes, even if the pool recovered by sample time
      (transient saturation, the corrected #333 wedge mechanism).

    Never raises: sampling must not turn a passing readiness probe into
    a failure.
    """

    def __init__(self, interval: float = SATURATION_LOG_INTERVAL) -> None:
        self._interval = interval
        self._last_warn: dict[str, float] = {}
        self._last_queued: dict[str, int] = {}

    def sample(self, alias: str, pool: Any) -> None:
        try:
            stats = pool.get_stats()
        except Exception:  # pragma: no cover - never mask the probe
            return
        try:
            available = int(stats.get("pool_available", 1))
            size = int(stats.get("pool_size", 0))
            max_size = int(stats.get("pool_max", 0))
            queued = int(stats.get("requests_queued", 0))
        except (TypeError, ValueError):  # pragma: no cover - defensive
            return
        previous = self._last_queued.get(alias)
        self._last_queued[alias] = queued
        clients_queued = previous is not None and queued > previous
        saturated = size > 0 and available == 0
        if not (saturated or clients_queued):
            return
        now = time.monotonic()
        if now - self._last_warn.get(alias, 0.0) < self._interval:
            return
        self._last_warn[alias] = now
        logger.warning(
            "psycopg pool saturation (%s): %s/%s connections available, "
            "%s checked out, %s clients queued total%s",
            alias,
            available,
            max_size,
            # Clamp: _get_measures() reads size/available without a lock;
            # a torn read could momentarily invert the pair (cosmetic nit
            # from the #334 review) — never render a negative count.
            max(0, size - available),
            queued,
            " [clients queued since the last probe]" if clients_queued else "",
        )


#: Module sampler shared by the readiness probes (one per process).
_sampler = PoolSaturationSampler()


def sample_pool_saturation(alias: str, pool: Any) -> None:
    """Sample pool saturation from a readiness probe (never raises)."""
    _sampler.sample(alias, pool)


class PoolStatsDatabaseCheck(DatabaseHeartBeatCheck):
    """``DatabaseHeartBeatCheck`` that logs psycopg pool stats on failure.

    No-op (and no extra output) when pooling is not enabled
    (``POSTGRES_POOL`` unset — ``connections[alias].pool`` is ``None``).
    """

    @override
    def check_status(self) -> None:
        try:
            super().check_status()
        except BaseException:
            self._log_pool_stats()
            raise

    def _log_pool_stats(self) -> None:
        try:
            # None unless the psycopg3 pool is configured (POSTGRES_POOL=1);
            # the attribute only exists on the psycopg backend wrapper.
            pool = getattr(connections[self.alias], "pool", None)
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

    @override
    def check_status(self) -> None:
        pool = self._pool_or_none()
        if pool is not None:
            self._check_via_pool(pool)
            # The probe doubles as a saturation sample (issue #333):
            # warn while requests still pass but the pool runs hot.
            sample_pool_saturation(self.alias, pool)
            return
        self._check_via_thread()

    def _pool_or_none(self):
        try:
            # The ``pool`` attribute exists only on the psycopg backend
            # wrapper (POSTGRES_POOL=1); None everywhere else.
            return getattr(connections[self.alias], "pool", None)
        except Exception:  # pragma: no cover - fall back to the heartbeat
            return None

    def _check_via_pool(self, pool: Any) -> None:
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
            # Checkout timeout = the wedge symptom. Capture the pool's own
            # stats at the exact moment (issue #333): the deep check logs
            # them too, but readiness failures repeat every probe.
            try:
                logger.error(
                    "psycopg pool checkout exceeded %ss (%s): stats=%s",
                    self.budget_seconds,
                    self.alias,
                    pool.get_stats(),
                )
            except Exception:  # pragma: no cover - never mask the failure
                pass
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
        outcome: dict[str, Any] = {}

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

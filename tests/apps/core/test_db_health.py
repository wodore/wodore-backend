"""Tests for the DB health checks (pool stats + fast readiness budget)."""

import time

import pytest
from health_check.exceptions import ServiceUnavailable
from psycopg_pool import PoolTimeout

from server.core.db_health import FastDatabaseReadinessCheck


class _FakePool:
    """Minimal psycopg_pool stand-in for the readiness check."""

    def __init__(self, *, checkout_delay: float = 0.0, row=(1,), opened=True):
        self.checkout_delay = checkout_delay
        self.row = row
        self.putconn_calls = 0
        self.open_calls = 0
        self._opened = opened

    def open(self):
        self.open_calls += 1
        self._opened = True

    def getconn(self, timeout=None):
        if not self._opened:
            raise RuntimeError("the pool 'pool-1' is not open yet")
        if timeout is not None and self.checkout_delay > timeout:
            # Emulate psycopg_pool: wait out the budget, then raise.
            time.sleep(timeout)
            raise PoolTimeout(f"couldn't get a connection after {timeout:.2f} sec")
        time.sleep(self.checkout_delay)
        return self

    def putconn(self, conn):
        self.putconn_calls += 1

    def execute(self, query):
        class _Cursor:
            def fetchone(self_inner):
                return self.row

        return _Cursor()


class TestFastDatabaseReadinessCheck:
    def test_pool_path_opens_a_lazy_pool_before_checking_out(self):
        # Freshly booted worker: Django creates the pool with open=False;
        # the check must open it (like Django does) instead of failing with
        # "the pool ... is not open yet" (seen on staging 2026-10-06).
        pool = _FakePool(opened=False)
        check = FastDatabaseReadinessCheck(budget_seconds=2.0)

        def _pool():
            return pool

        check._pool_or_none = _pool
        check.check_status()
        assert pool.open_calls == 1
        assert pool.putconn_calls == 1

    def test_pool_path_succeeds_and_returns_connection(self):
        pool = _FakePool()
        check = FastDatabaseReadinessCheck(budget_seconds=2.0)

        def _pool():
            return pool

        check._pool_or_none = _pool
        check.check_status()
        assert pool.putconn_calls == 1

    def test_pool_path_fails_fast_when_checkout_exceeds_budget(self):
        # 1s checkout vs 0.2s budget: the check must give up quickly.
        pool = _FakePool(checkout_delay=1.0)
        check = FastDatabaseReadinessCheck(budget_seconds=0.2)

        def _pool():
            return pool

        check._pool_or_none = _pool
        started = time.monotonic()
        with pytest.raises(ServiceUnavailable) as excinfo:
            check.check_status()
        elapsed = time.monotonic() - started
        assert elapsed < 0.9, f"check took {elapsed:.2f}s, budget was 0.2s"
        assert "pool checkout exceeded" in str(excinfo.value)

    def test_thread_path_fails_fast_when_db_does_not_answer(self, monkeypatch):
        from health_check.contrib.db_heartbeat.backends import (
            DatabaseHeartBeatCheck,
        )

        def _slow(self):
            time.sleep(1.0)

        monkeypatch.setattr(DatabaseHeartBeatCheck, "check_status", _slow)
        check = FastDatabaseReadinessCheck(budget_seconds=0.2)
        started = time.monotonic()
        with pytest.raises(ServiceUnavailable) as excinfo:
            check.check_status()
        elapsed = time.monotonic() - started
        assert elapsed < 0.9, f"check took {elapsed:.2f}s, budget was 0.2s"
        assert "not answering within" in str(excinfo.value)

    def test_thread_path_propagates_db_errors(self, monkeypatch):
        from health_check.contrib.db_heartbeat.backends import (
            DatabaseHeartBeatCheck,
        )

        def _broken(self):
            raise ServiceUnavailable("boom")

        monkeypatch.setattr(DatabaseHeartBeatCheck, "check_status", _broken)
        check = FastDatabaseReadinessCheck(budget_seconds=2.0)
        with pytest.raises(ServiceUnavailable, match="boom"):
            check.check_status()


class TestReadyEndpoint:
    @pytest.mark.django_db
    def test_ready_endpoint_answers_200_quickly(self, client):
        response = client.get("/health/ready/", HTTP_HOST="localhost")
        assert response.status_code == 200

    def test_ready_endpoint_is_wired(self, client):
        # Cheap routing assertion without touching the DB: as_view kwargs
        # land on the resolved callback, not the class attribute.
        from django.urls import resolve

        match = resolve("/health/ready/")
        assert match.func.view_class.__name__ == "HealthCheckView"
        checks = match.func.view_initkwargs["checks"]
        assert checks, "readiness view must run at least one check"
        check_class, options = checks[0]
        assert check_class is FastDatabaseReadinessCheck
        assert options == {"budget_seconds": 2.0}

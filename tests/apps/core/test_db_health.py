"""Tests for the DB health checks (pool stats + fast readiness budget)."""

import time
from collections.abc import Callable
from typing import Any

import pytest
from health_check.exceptions import ServiceUnavailable
from psycopg_pool import PoolTimeout

from django.test import Client

from server.core.db_health import FastDatabaseReadinessCheck


def _record_warning(sink: list[tuple[str, tuple[Any, ...]]]) -> Callable[..., None]:
    """Logger-method stand-in recording ``(msg, args)`` tuples into ``sink``."""

    def _record(msg: str, *args: Any, **kwargs: Any) -> None:
        sink.append((msg, args))

    return _record


class _FakePool:
    """Minimal psycopg_pool stand-in for the readiness check."""

    def __init__(
        self,
        *,
        checkout_delay: float = 0.0,
        row: tuple[int, ...] = (1,),
        opened: bool = True,
    ):
        self.checkout_delay = checkout_delay
        self.row = row
        self.putconn_calls = 0
        self.open_calls = 0
        self._opened = opened

    def open(self):
        self.open_calls += 1
        self._opened = True

    def getconn(self, timeout: float | None = None):
        if not self._opened:
            raise RuntimeError("the pool 'pool-1' is not open yet")
        if timeout is not None and self.checkout_delay > timeout:
            # Emulate psycopg_pool: wait out the budget, then raise.
            time.sleep(timeout)
            raise PoolTimeout(f"couldn't get a connection after {timeout:.2f} sec")
        time.sleep(self.checkout_delay)
        return self

    def putconn(self, conn: object):
        self.putconn_calls += 1

    def execute(self, query: str):
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

        check._pool_or_none = _pool  # type: ignore  # test stub replaces the pool accessor
        check.check_status()
        assert pool.open_calls == 1
        assert pool.putconn_calls == 1

    def test_pool_path_succeeds_and_returns_connection(self):
        pool = _FakePool()
        check = FastDatabaseReadinessCheck(budget_seconds=2.0)

        def _pool():
            return pool

        check._pool_or_none = _pool  # type: ignore  # test stub replaces the pool accessor
        check.check_status()
        assert pool.putconn_calls == 1

    def test_pool_path_fails_fast_when_checkout_exceeds_budget(self):
        # 1s checkout vs 0.2s budget: the check must give up quickly.
        pool = _FakePool(checkout_delay=1.0)
        check = FastDatabaseReadinessCheck(budget_seconds=0.2)

        def _pool():
            return pool

        check._pool_or_none = _pool  # type: ignore  # test stub replaces the pool accessor
        started = time.monotonic()
        with pytest.raises(ServiceUnavailable) as excinfo:
            check.check_status()
        elapsed = time.monotonic() - started
        assert elapsed < 0.9, f"check took {elapsed:.2f}s, budget was 0.2s"
        assert "pool checkout exceeded" in str(excinfo.value)

    def test_thread_path_fails_fast_when_db_does_not_answer(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        from health_check.contrib.db_heartbeat.backends import (
            DatabaseHeartBeatCheck,
        )

        def _slow(self: DatabaseHeartBeatCheck):
            time.sleep(1.0)

        monkeypatch.setattr(DatabaseHeartBeatCheck, "check_status", _slow)
        check = FastDatabaseReadinessCheck(budget_seconds=0.2)
        started = time.monotonic()
        with pytest.raises(ServiceUnavailable) as excinfo:
            check.check_status()
        elapsed = time.monotonic() - started
        assert elapsed < 0.9, f"check took {elapsed:.2f}s, budget was 0.2s"
        assert "not answering within" in str(excinfo.value)

    def test_thread_path_propagates_db_errors(self, monkeypatch: pytest.MonkeyPatch):
        from health_check.contrib.db_heartbeat.backends import (
            DatabaseHeartBeatCheck,
        )

        def _broken(self: DatabaseHeartBeatCheck):
            raise ServiceUnavailable("boom")

        monkeypatch.setattr(DatabaseHeartBeatCheck, "check_status", _broken)
        check = FastDatabaseReadinessCheck(budget_seconds=2.0)
        with pytest.raises(ServiceUnavailable, match="boom"):
            check.check_status()


class TestReadyEndpoint:
    @pytest.mark.django_db
    def test_ready_endpoint_answers_200_quickly(self, client: Client):
        response = client.get("/health/ready/", HTTP_HOST="localhost")
        assert response.status_code == 200

    def test_ready_endpoint_is_wired(self, client: Client):
        # Cheap routing assertion without touching the DB: as_view kwargs
        # land on the resolved callback, not the class attribute.
        from django.urls import resolve

        match = resolve("/health/ready/")
        assert match.func.view_class.__name__ == "HealthCheckView"  # type: ignore  # dynamic attr: plugin-less inference gap
        checks = match.func.view_initkwargs["checks"]  # type: ignore  # dynamic attr: plugin-less inference gap
        assert checks, "readiness view must run at least one check"
        check_class, options = checks[0]
        assert check_class is FastDatabaseReadinessCheck
        assert options == {"budget_seconds": 2.0}


class _StatsPool(_FakePool):
    """_FakePool with configurable ``get_stats()`` payloads."""

    def __init__(self, *, stats: dict[str, Any] | None = None, **kwargs: Any):
        super().__init__(**kwargs)
        self.stats = stats or {}

    def get_stats(self):
        return dict(self.stats)


class TestPoolSaturationSampler:
    """Issue #333: probe-driven sampling warns before the wedge bites."""

    def _healthy_stats(self, **overrides: Any):
        return {
            "pool_min": 2,
            "pool_max": 5,
            "pool_size": 2,
            "pool_available": 2,
            "requests_queued": 0,
            **overrides,
        }

    def test_healthy_pool_stays_silent(self, monkeypatch: pytest.MonkeyPatch):
        from server.core import db_health

        calls = []
        monkeypatch.setattr(db_health.logger, "warning", _record_warning(calls))
        db_health.PoolSaturationSampler().sample(
            "default", _StatsPool(stats=self._healthy_stats())
        )
        assert not calls

    def test_fully_checked_out_pool_warns(self, monkeypatch: pytest.MonkeyPatch):
        from server.core import db_health

        calls = []
        monkeypatch.setattr(db_health.logger, "warning", _record_warning(calls))
        db_health.PoolSaturationSampler().sample(
            "default",
            _StatsPool(stats=self._healthy_stats(pool_size=5, pool_available=0)),
        )
        assert len(calls) == 1
        rendered = calls[0][0] % calls[0][1]
        assert "psycopg pool saturation (default)" in rendered
        assert "0/5 connections available" in rendered
        assert "5 checked out" in rendered

    def test_warning_is_rate_limited(self, monkeypatch: pytest.MonkeyPatch):
        from server.core import db_health

        calls = []
        monkeypatch.setattr(db_health.logger, "warning", _record_warning(calls))
        sampler = db_health.PoolSaturationSampler()
        pool = _StatsPool(stats=self._healthy_stats(pool_size=5, pool_available=0))
        sampler.sample("default", pool)
        sampler.sample("default", pool)
        assert len(calls) == 1

    def test_rising_queued_counter_warns_even_after_recovery(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Transient saturation: clients queued between probes, but the
        pool has slots again by sample time — the counter delta catches
        it (the corrected #333 mechanism: storms saturate transiently)."""
        from server.core import db_health

        calls = []
        monkeypatch.setattr(db_health.logger, "warning", _record_warning(calls))
        sampler = db_health.PoolSaturationSampler()
        sampler.sample("default", _StatsPool(stats=self._healthy_stats()))
        sampler.sample(
            "default",
            _StatsPool(stats=self._healthy_stats(requests_queued=3)),
        )
        assert len(calls) == 1
        rendered = calls[0][0] % calls[0][1]
        assert "clients queued since the last probe" in rendered

    def test_sampler_never_raises_on_broken_stats(self):
        from server.core.db_health import PoolSaturationSampler

        class _Broken:
            def get_stats(self):
                raise RuntimeError("pool closed")

        PoolSaturationSampler().sample("default", _Broken())  # no raise

    def test_boot_with_zero_connections_stays_silent(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """pool_size == 0 before the pool has grown (min_size not yet
        reached): available == 0 must NOT read as saturation."""
        from server.core import db_health

        calls = []
        monkeypatch.setattr(db_health.logger, "warning", _record_warning(calls))
        db_health.PoolSaturationSampler().sample(
            "default",
            _StatsPool(stats=self._healthy_stats(pool_size=0, pool_available=0)),
        )
        assert not calls

    def test_none_stat_values_never_raise(self):
        """Malformed stat payloads (None values) skip the sample silently
        instead of poisoning the readiness probe."""
        from server.core.db_health import PoolSaturationSampler

        PoolSaturationSampler().sample(
            "default", _StatsPool(stats={"pool_size": None, "pool_available": None})
        )  # no raise

    def test_rate_limit_window_reopens(self, monkeypatch: pytest.MonkeyPatch):
        """A zero interval keeps the window open — each saturated sample
        warns (the clamp on the reopen path, mirrored from the 60s default
        where reopening after the interval must warn again)."""
        from server.core import db_health

        calls = []
        monkeypatch.setattr(db_health.logger, "warning", _record_warning(calls))
        sampler = db_health.PoolSaturationSampler(interval=0.0)
        pool = _StatsPool(stats=self._healthy_stats(pool_size=5, pool_available=0))
        sampler.sample("default", pool)
        sampler.sample("default", pool)
        assert len(calls) == 2

    def test_readiness_failure_logs_pool_stats(self, caplog: pytest.LogCaptureFixture):
        """A checkout timeout must capture the pool stats at the exact
        moment — the evidence both wedge incidents lacked."""
        pool = _StatsPool(
            stats=self._healthy_stats(pool_size=5, pool_available=0),
            checkout_delay=5.0,
        )
        check = FastDatabaseReadinessCheck(budget_seconds=0.05)
        from unittest import mock

        from server.core import db_health

        errors = []
        with (
            mock.patch.object(type(check), "_pool_or_none", return_value=pool),
            mock.patch.object(db_health.logger, "error", _record_warning(errors)),
        ):
            with pytest.raises(ServiceUnavailable, match="checkout exceeded"):
                check.check_status()
        assert len(errors) == 1
        rendered = errors[0][0] % errors[0][1]
        assert "stats=" in rendered
        assert "'pool_available': 0" in rendered

    def test_successful_probe_samples_saturation(
        self, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ):
        from server.core import db_health

        captured: dict[str, Any] = {}

        def _capture(alias: str, pool: Any):
            captured["alias"] = alias
            captured["stats"] = pool.get_stats()

        monkeypatch.setattr(db_health, "_sampler", db_health.PoolSaturationSampler())
        monkeypatch.setattr(db_health, "sample_pool_saturation", _capture)
        # The check_status closure calls the module function by name —
        # patch the module attribute the check resolves at call time.
        pool = _StatsPool(stats=self._healthy_stats())
        check = FastDatabaseReadinessCheck(budget_seconds=2.0)

        def _pool_of(_self: object) -> _StatsPool:
            return pool

        monkeypatch.setattr(type(check), "_pool_or_none", _pool_of, raising=True)
        with caplog.at_level("WARNING"):
            check.check_status()
        assert captured["alias"] == "default"
        assert captured["stats"]["pool_available"] == 2

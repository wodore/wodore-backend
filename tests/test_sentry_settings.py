"""Tests for the error-tracking settings component (openspec: add-error-tracking).

Semantics under test (spec: error-tracking):

- DSN gating: no ``SENTRY_DSN`` -> ``sentry_sdk.init`` is never called;
  the suite itself runs DSN-free, so the SDK stays inactive in-process
- with a DSN: ``release=GIT_HASH`` (uniform across environments),
  ``environment`` from ``SENTRY_ENVIRONMENT`` / ``DJANGO_ENV``,
  ``send_default_pii=False``, logging + asyncio integrations,
  traces sampler excluding ``/health/`` and honoring
  ``SENTRY_TRACES_SAMPLE_RATE`` (0 = errors-only)
- ``before_send`` attaches the package semver as ``app_version``

The component is reloaded with ``sentry_sdk.init`` monkeypatched to a
recorder — no real client, no network.
"""

import importlib

import pytest
import sentry_sdk

sentry_comp = importlib.import_module("server.settings.components.sentry")


@pytest.fixture
def recorded_init(monkeypatch):
    """Reload the component with sentry_sdk.init replaced by a recorder.

    Returns the list the captured kwargs dicts are appended to.
    """
    calls: list[dict] = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: calls.append(kwargs))
    return calls


def _reload():
    return importlib.reload(sentry_comp)


@pytest.fixture(autouse=True)
def _restore_module():
    """Reload the module after each test so recorded init calls don't leak."""
    yield
    importlib.reload(sentry_comp)


class TestDsnGating:
    def test_no_dsn_skips_init(self, monkeypatch, recorded_init):
        monkeypatch.delenv("SENTRY_DSN", raising=False)

        _reload()

        assert recorded_init == []

    def test_settings_import_left_sdk_inactive(self):
        # This suite runs under DJANGO_ENV=test with no DSN configured;
        # the full settings import (done by pytest-django) must not have
        # initialized the SDK.
        assert sentry_sdk.get_client().is_active() is False

    def test_empty_dsn_skips_init(self, monkeypatch, recorded_init):
        monkeypatch.setenv("SENTRY_DSN", "")

        _reload()

        assert recorded_init == []


class TestInitOptions:
    def test_release_is_git_hash_and_pii_off(self, monkeypatch, recorded_init):
        monkeypatch.setenv("SENTRY_DSN", "https://key@localhost/1")
        monkeypatch.setenv("GIT_HASH", "abc123def456")

        _reload()

        assert len(recorded_init) == 1
        kwargs = recorded_init[0]
        assert kwargs["dsn"] == "https://key@localhost/1"
        # Deploy-exact identity, uniform across environments:
        assert kwargs["release"] == "abc123def456"
        assert kwargs["send_default_pii"] is False

    def test_environment_defaults_to_django_env(self, monkeypatch, recorded_init):
        monkeypatch.setenv("SENTRY_DSN", "https://key@localhost/1")
        monkeypatch.setenv("DJANGO_ENV", "staging")

        _reload()

        assert recorded_init[0]["environment"] == "staging"

    def test_sentry_environment_overrides(self, monkeypatch, recorded_init):
        monkeypatch.setenv("SENTRY_DSN", "https://key@localhost/1")
        monkeypatch.setenv("DJANGO_ENV", "production")
        monkeypatch.setenv("SENTRY_ENVIRONMENT", "production-eu")

        _reload()

        assert recorded_init[0]["environment"] == "production-eu"

    def test_integrations_present(self, monkeypatch, recorded_init):
        monkeypatch.setenv("SENTRY_DSN", "https://key@localhost/1")

        _reload()

        integrations = {type(i).__name__ for i in recorded_init[0]["integrations"]}
        assert "LoggingIntegration" in integrations
        assert "AsyncioIntegration" in integrations


class TestTracesSampler:
    """Sampler tests use the sampling-context shapes the real SDK passes:

    - WSGI (gunicorn default): ``{"wsgi_environ": <environ>}`` — the
      transaction *name* is still ``"generic WSGI request"`` at sampling
      time, so name-based matching would never fire
    - ASGI (ASGI_ENABLED=1): ``{"asgi_scope": <scope>}`` — names are
      full URLs there
    """

    def test_wsgi_health_checks_never_traced(self, monkeypatch, recorded_init):
        monkeypatch.setenv("SENTRY_DSN", "https://key@localhost/1")

        _reload()

        sampler = recorded_init[0]["traces_sampler"]
        ctx = {
            "wsgi_environ": {"PATH_INFO": "/health/complete/", "REQUEST_METHOD": "GET"}
        }
        assert sampler(ctx) == 0.0

    def test_asgi_health_checks_never_traced(self, monkeypatch, recorded_init):
        monkeypatch.setenv("SENTRY_DSN", "https://key@localhost/1")

        _reload()

        sampler = recorded_init[0]["traces_sampler"]
        ctx = {"asgi_scope": {"type": "http", "path": "/health/ready/"}}
        assert sampler(ctx) == 0.0

    def test_unresolved_wsgi_name_does_not_match(self, monkeypatch, recorded_init):
        # Regression guard for the review finding: matching on
        # transaction_context.name ("generic WSGI request" at sampling
        # time) must not accidentally exclude (or fail to exclude)
        # anything — the path comes from wsgi_environ/asgi_scope.
        monkeypatch.setenv("SENTRY_DSN", "https://key@localhost/1")

        _reload()

        sampler = recorded_init[0]["traces_sampler"]
        assert (
            sampler({"transaction_context": {"name": "generic WSGI request"}}) == 0.05
        )

    def test_default_rate_applies_to_api_requests(self, monkeypatch, recorded_init):
        monkeypatch.setenv("SENTRY_DSN", "https://key@localhost/1")
        monkeypatch.delenv("SENTRY_TRACES_SAMPLE_RATE", raising=False)

        _reload()

        sampler = recorded_init[0]["traces_sampler"]
        assert sampler({"wsgi_environ": {"PATH_INFO": "/v1/huts/"}}) == 0.05

    def test_non_http_transactions_fall_back_to_name(self, monkeypatch, recorded_init):
        monkeypatch.setenv("SENTRY_DSN", "https://key@localhost/1")

        _reload()

        sampler = recorded_init[0]["traces_sampler"]
        assert sampler({"transaction_context": {"name": "/health/manual-job/"}}) == 0.0

    def test_rate_configurable_and_zero_disables(self, monkeypatch, recorded_init):
        monkeypatch.setenv("SENTRY_DSN", "https://key@localhost/1")
        monkeypatch.setenv("SENTRY_TRACES_SAMPLE_RATE", "0.5")

        _reload()

        sampler = recorded_init[0]["traces_sampler"]
        assert sampler({"wsgi_environ": {"PATH_INFO": "/v1/huts/"}}) == 0.5

        monkeypatch.setenv("SENTRY_TRACES_SAMPLE_RATE", "0")
        _reload()
        sampler = recorded_init[1]["traces_sampler"]
        assert sampler({"wsgi_environ": {"PATH_INFO": "/v1/huts/"}}) == 0.0


class TestBeforeSend:
    def test_app_version_tag_attached(self, monkeypatch, recorded_init):
        from importlib.metadata import version

        monkeypatch.setenv("SENTRY_DSN", "https://key@localhost/1")

        _reload()

        before_send = recorded_init[0]["before_send"]
        event = before_send({}, {})
        assert event["tags"]["app_version"] == version("wodore-backend")

    def test_shielded_cancellederror_dropped(self, monkeypatch, recorded_init):
        # Issue 154471293: py3.14's rewritten asyncio.shield logs
        # "CancelledError exception in shielded future" when uvicorn
        # cancels the request task on client disconnect and asgiref's
        # bridge surfaces CancelledError on the shielded future. Client
        # aborts are not actionable — before_send must drop them.
        monkeypatch.setenv("SENTRY_DSN", "https://key@localhost/1")

        _reload()

        before_send = recorded_init[0]["before_send"]
        event = {
            "logger": "asyncio",
            "logentry": {"message": "CancelledError exception in shielded future"},
            "exception": {
                "values": [
                    {
                        "type": "CancelledError",
                        "value": "",
                        "mechanism": {"type": "logging", "handled": True},
                    }
                ]
            },
        }
        assert before_send(event, {}) is None

    def test_shielded_real_exception_kept(self, monkeypatch, recorded_init):
        # Same asyncio logger and message shape, but a non-CancelledError
        # exception: genuine failure inside shielded work — must pass.
        monkeypatch.setenv("SENTRY_DSN", "https://key@localhost/1")

        _reload()

        before_send = recorded_init[0]["before_send"]
        event = {
            "logger": "asyncio",
            "logentry": {"message": "ValueError exception in shielded future"},
            "exception": {
                "values": [
                    {
                        "type": "ValueError",
                        "value": "boom",
                        "mechanism": {"type": "logging", "handled": True},
                    }
                ]
            },
        }
        assert "tags" in before_send(event, {})

    def test_cancellederror_outside_asyncio_logger_kept(
        self, monkeypatch, recorded_init
    ):
        # A CancelledError reported by anything but the asyncio logger
        # (e.g. app code) is not shield noise — must pass through.
        monkeypatch.setenv("SENTRY_DSN", "https://key@localhost/1")

        _reload()

        before_send = recorded_init[0]["before_send"]
        event = {
            "exception": {
                "values": [
                    {
                        "type": "CancelledError",
                        "value": "task cancelled",
                        "mechanism": {"type": "logging", "handled": True},
                    }
                ]
            },
        }
        assert "tags" in before_send(event, {})

    def test_asyncio_unretrieved_future_exception_kept(
        self, monkeypatch, recorded_init
    ):
        # Other asyncio-loop reports (e.g. unretrieved future exceptions)
        # stay visible — the filter is scoped to the shield message.
        monkeypatch.setenv("SENTRY_DSN", "https://key@localhost/1")

        _reload()

        before_send = recorded_init[0]["before_send"]
        event = {
            "logger": "asyncio",
            "logentry": {"message": "Future exception was never retrieved"},
            "exception": {
                "values": [
                    {
                        "type": "CancelledError",
                        "value": "",
                        "mechanism": {"type": "logging", "handled": True},
                    }
                ]
            },
        }
        assert "tags" in before_send(event, {})

    def test_app_version_tag_attached_to_transactions(self, monkeypatch, recorded_init):
        from importlib.metadata import version

        monkeypatch.setenv("SENTRY_DSN", "https://key@localhost/1")

        _reload()

        before_send_transaction = recorded_init[0]["before_send_transaction"]
        event = before_send_transaction({"type": "transaction"}, {})
        assert event["tags"]["app_version"] == version("wodore-backend")


class TestQ2ErrorReporter:
    """django-q2 swallows task exceptions (stored as string results, no
    ERROR log); the in-repo reporter bridges them to the SDK."""

    def test_cluster_wires_reporter(self):
        # Q_CLUSTER carries the reporter config; django_q.conf loads it at
        # import into the module-level error_reporter.
        from django.conf import settings

        assert settings.Q_CLUSTER["error_reporter"] == {"wodore-sentry": {}}

        import django_q.conf as qconf

        error_reporter = getattr(qconf, "error_reporter", None)
        assert error_reporter is not None
        targets = [type(t).__name__ for t in getattr(error_reporter, "targets", [])]
        assert "SentryErrorReporter" in targets

    def test_report_noop_without_active_client(self, monkeypatch):
        import sentry_sdk

        from server.core.q2_sentry import SentryErrorReporter

        assert sentry_sdk.get_client().is_active() is False  # test env: no DSN
        called = []
        monkeypatch.setattr(
            sentry_sdk, "capture_exception", lambda *a, **k: called.append(a)
        )

        try:
            raise RuntimeError("boom")
        except RuntimeError:
            SentryErrorReporter().report()

        assert called == []  # inert: SDK not active in dev/test/CI

    def test_report_captures_live_exception_when_active(self, monkeypatch):
        import sentry_sdk

        from server.core.q2_sentry import SentryErrorReporter

        monkeypatch.setattr(
            sentry_sdk,
            "get_client",
            lambda: type("C", (), {"is_active": lambda self: True})(),
        )
        captured = []
        monkeypatch.setattr(
            sentry_sdk,
            "capture_exception",
            lambda *a, **k: captured.append(a),
        )

        try:
            raise ValueError("task failed")
        except ValueError:
            SentryErrorReporter().report()

        # capture_exception() with no args must pick up the live
        # sys.exc_info() — this is the reporter's whole point.
        assert captured == [()]

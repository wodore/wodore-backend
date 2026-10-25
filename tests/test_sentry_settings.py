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
from typing import Any

import pytest
import sentry_sdk

sentry_comp = importlib.import_module("server.settings.components.sentry")


class _ActiveClient:
    """Minimal sentry client stub reporting an active SDK."""

    def is_active(self) -> bool:
        return True


@pytest.fixture
def recorded_init(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Reload the component with sentry_sdk.init replaced by a recorder.

    Returns the list the captured kwargs dicts are appended to.
    """
    calls: list[dict[str, Any]] = []

    def _init(**kwargs: Any) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(sentry_sdk, "init", _init)
    return calls


def _reload():
    return importlib.reload(sentry_comp)


@pytest.fixture(autouse=True)
def _restore_module():
    """Reload the module after each test so recorded init calls don't leak."""
    yield
    importlib.reload(sentry_comp)


class TestDsnGating:
    def test_no_dsn_skips_init(
        self, monkeypatch: pytest.MonkeyPatch, recorded_init: list[dict[str, Any]]
    ):
        monkeypatch.delenv("SENTRY_DSN", raising=False)

        _reload()

        assert recorded_init == []

    def test_settings_import_left_sdk_inactive(self):
        # This suite runs under DJANGO_ENV=test with no DSN configured;
        # the full settings import (done by pytest-django) must not have
        # initialized the SDK.
        assert sentry_sdk.get_client().is_active() is False

    def test_empty_dsn_skips_init(
        self, monkeypatch: pytest.MonkeyPatch, recorded_init: list[dict[str, Any]]
    ):
        monkeypatch.setenv("SENTRY_DSN", "")

        _reload()

        assert recorded_init == []


class TestInitOptions:
    def test_release_is_git_hash_and_pii_off(
        self, monkeypatch: pytest.MonkeyPatch, recorded_init: list[dict[str, Any]]
    ):
        monkeypatch.setenv("SENTRY_DSN", "https://key@localhost/1")
        monkeypatch.setenv("GIT_HASH", "abc123def456")

        _reload()

        assert len(recorded_init) == 1
        kwargs = recorded_init[0]
        assert kwargs["dsn"] == "https://key@localhost/1"
        # Deploy-exact identity, uniform across environments:
        assert kwargs["release"] == "abc123def456"
        assert kwargs["send_default_pii"] is False

    def test_environment_defaults_to_django_env(
        self, monkeypatch: pytest.MonkeyPatch, recorded_init: list[dict[str, Any]]
    ):
        monkeypatch.setenv("SENTRY_DSN", "https://key@localhost/1")
        monkeypatch.setenv("DJANGO_ENV", "staging")

        _reload()

        assert recorded_init[0]["environment"] == "staging"

    def test_sentry_environment_overrides(
        self, monkeypatch: pytest.MonkeyPatch, recorded_init: list[dict[str, Any]]
    ):
        monkeypatch.setenv("SENTRY_DSN", "https://key@localhost/1")
        monkeypatch.setenv("DJANGO_ENV", "production")
        monkeypatch.setenv("SENTRY_ENVIRONMENT", "production-eu")

        _reload()

        assert recorded_init[0]["environment"] == "production-eu"

    def test_integrations_present(
        self, monkeypatch: pytest.MonkeyPatch, recorded_init: list[dict[str, Any]]
    ):
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

    def test_wsgi_health_checks_never_traced(
        self, monkeypatch: pytest.MonkeyPatch, recorded_init: list[dict[str, Any]]
    ):
        monkeypatch.setenv("SENTRY_DSN", "https://key@localhost/1")

        _reload()

        sampler = recorded_init[0]["traces_sampler"]
        ctx = {
            "wsgi_environ": {"PATH_INFO": "/health/complete/", "REQUEST_METHOD": "GET"}
        }
        assert sampler(ctx) == 0.0

    def test_asgi_health_checks_never_traced(
        self, monkeypatch: pytest.MonkeyPatch, recorded_init: list[dict[str, Any]]
    ):
        monkeypatch.setenv("SENTRY_DSN", "https://key@localhost/1")

        _reload()

        sampler = recorded_init[0]["traces_sampler"]
        ctx = {"asgi_scope": {"type": "http", "path": "/health/ready/"}}
        assert sampler(ctx) == 0.0

    def test_unresolved_wsgi_name_does_not_match(
        self, monkeypatch: pytest.MonkeyPatch, recorded_init: list[dict[str, Any]]
    ):
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

    def test_default_rate_applies_to_api_requests(
        self, monkeypatch: pytest.MonkeyPatch, recorded_init: list[dict[str, Any]]
    ):
        monkeypatch.setenv("SENTRY_DSN", "https://key@localhost/1")
        monkeypatch.delenv("SENTRY_TRACES_SAMPLE_RATE", raising=False)

        _reload()

        sampler = recorded_init[0]["traces_sampler"]
        assert sampler({"wsgi_environ": {"PATH_INFO": "/v1/huts/"}}) == 0.05

    def test_non_http_transactions_fall_back_to_name(
        self, monkeypatch: pytest.MonkeyPatch, recorded_init: list[dict[str, Any]]
    ):
        monkeypatch.setenv("SENTRY_DSN", "https://key@localhost/1")

        _reload()

        sampler = recorded_init[0]["traces_sampler"]
        assert sampler({"transaction_context": {"name": "/health/manual-job/"}}) == 0.0

    def test_rate_configurable_and_zero_disables(
        self, monkeypatch: pytest.MonkeyPatch, recorded_init: list[dict[str, Any]]
    ):
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
    def test_app_version_tag_attached(
        self, monkeypatch: pytest.MonkeyPatch, recorded_init: list[dict[str, Any]]
    ):
        from importlib.metadata import version

        monkeypatch.setenv("SENTRY_DSN", "https://key@localhost/1")

        _reload()

        before_send = recorded_init[0]["before_send"]
        event = before_send({}, {})
        assert event["tags"]["app_version"] == version("wodore-backend")

    def test_shielded_cancellederror_dropped(
        self, monkeypatch: pytest.MonkeyPatch, recorded_init: list[dict[str, Any]]
    ):
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

    def test_shielded_real_exception_kept(
        self, monkeypatch: pytest.MonkeyPatch, recorded_init: list[dict[str, Any]]
    ):
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
        self, monkeypatch: pytest.MonkeyPatch, recorded_init: list[dict[str, Any]]
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
        self, monkeypatch: pytest.MonkeyPatch, recorded_init: list[dict[str, Any]]
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

    def test_current_thread_executor_disconnect_noise_dropped(
        self, monkeypatch: pytest.MonkeyPatch, recorded_init: list[dict[str, Any]]
    ):
        # Issue 155259431: Django 6.1 races disconnect-listening against
        # response processing in a TaskGroup; on a mid-request client
        # abort the response task is cancelled and the subsequent
        # request_finished dispatch (thread-sensitive sync_to_async)
        # hits the request's already-broken CurrentThreadExecutor.
        # Frames mirror the real staging event (ASGIHandler → dispatcher
        # asend → run_in_executor → CurrentThreadExecutor.submit). Not
        # actionable — dropped.
        monkeypatch.setenv("SENTRY_DSN", "https://key@localhost/1")

        _reload()

        before_send = recorded_init[0]["before_send"]
        event = {
            "exception": {
                "values": [
                    {
                        "type": "RuntimeError",
                        "value": "CurrentThreadExecutor already quit or is broken",
                        "mechanism": {"type": "asgi", "handled": False},
                        "stacktrace": {
                            "frames": [
                                {
                                    "function": "__call__",
                                    "module": "django.core.handlers.asgi",
                                    "filename": "django/core/handlers/asgi.py",
                                },
                                {
                                    "function": "handle",
                                    "module": "django.core.handlers.asgi",
                                    "filename": "django/core/handlers/asgi.py",
                                },
                                {
                                    "function": "asend",
                                    "module": "django.dispatch.dispatcher",
                                    "filename": "django/dispatch/dispatcher.py",
                                },
                                {
                                    "function": "run_in_executor",
                                    "module": "uvloop.loop",
                                    "filename": "uvloop/loop.pyx",
                                },
                                {
                                    "function": "submit",
                                    "module": "asgiref.current_thread_executor",
                                    "filename": "asgiref/current_thread_executor.py",
                                },
                            ]
                        },
                    }
                ]
            }
        }
        assert before_send(event, {}) is None

    def test_current_thread_executor_without_request_frames_kept(
        self, monkeypatch: pytest.MonkeyPatch, recorded_init: list[dict[str, Any]]
    ):
        # Same RuntimeError from application code (e.g. sync_to_async in
        # a fire-and-forget task outliving its request context —
        # asgiref#526's original report): no dispatcher/ASGIHandler
        # frames, so it is a genuine bug and must stay visible.
        monkeypatch.setenv("SENTRY_DSN", "https://key@localhost/1")

        _reload()

        before_send = recorded_init[0]["before_send"]
        event = {
            "exception": {
                "values": [
                    {
                        "type": "RuntimeError",
                        "value": "CurrentThreadExecutor already quit or is broken",
                        "mechanism": {"type": "generic", "handled": False},
                        "stacktrace": {
                            "frames": [
                                {
                                    "function": "submit",
                                    "module": "asgiref.current_thread_executor",
                                    "filename": "asgiref/current_thread_executor.py",
                                },
                                {
                                    "function": "run_background_job",
                                    "module": "server.apps.core.jobs",
                                    "filename": "server/apps/core/jobs.py",
                                },
                            ]
                        },
                    }
                ]
            }
        }
        assert "tags" in before_send(event, {})

    def test_other_runtimeerror_with_signal_frames_kept(
        self, monkeypatch: pytest.MonkeyPatch, recorded_init: list[dict[str, Any]]
    ):
        # The frame shape alone must not drop unrelated RuntimeErrors —
        # the message check is part of the filter.
        monkeypatch.setenv("SENTRY_DSN", "https://key@localhost/1")

        _reload()

        before_send = recorded_init[0]["before_send"]
        event = {
            "exception": {
                "values": [
                    {
                        "type": "RuntimeError",
                        "value": "You cannot submit onto CurrentThreadExecutor from its own thread",
                        "mechanism": {"type": "asgi", "handled": False},
                        "stacktrace": {
                            "frames": [
                                {
                                    "function": "handle",
                                    "module": "django.core.handlers.asgi",
                                    "filename": "django/core/handlers/asgi.py",
                                },
                                {
                                    "function": "asend",
                                    "module": "django.dispatch.dispatcher",
                                    "filename": "django/dispatch/dispatcher.py",
                                },
                            ]
                        },
                    }
                ]
            }
        }
        assert "tags" in before_send(event, {})

    def test_current_thread_executor_filename_only_frames_dropped(
        self, monkeypatch: pytest.MonkeyPatch, recorded_init: list[dict[str, Any]]
    ):
        # Some capture paths omit frame modules — the filename-suffix
        # fallback must still recognize the teardown path (absolute
        # paths as sentry-sdk reports them).
        monkeypatch.setenv("SENTRY_DSN", "https://key@localhost/1")

        _reload()

        before_send = recorded_init[0]["before_send"]
        event = {
            "exception": {
                "values": [
                    {
                        "type": "RuntimeError",
                        "value": "RuntimeError: CurrentThreadExecutor already quit or is broken",
                        "mechanism": {"type": "asgi", "handled": False},
                        "stacktrace": {
                            "frames": [
                                {
                                    "function": "asend",
                                    "filename": "/usr/local/lib/python3.14/site-packages/django/dispatch/dispatcher.py",
                                },
                                {
                                    "function": "__call__",
                                    "filename": "/usr/local/lib/python3.14/site-packages/django/core/handlers/asgi.py",
                                },
                            ]
                        },
                    }
                ]
            }
        }
        assert before_send(event, {}) is None

    def test_current_thread_executor_without_stacktrace_kept(
        self, monkeypatch: pytest.MonkeyPatch, recorded_init: list[dict[str, Any]]
    ):
        # Matching message but no stacktrace/frames: the filter fails
        # safe toward visibility — kept. Pins the default so a future
        # refactor that inverts it trips here.
        monkeypatch.setenv("SENTRY_DSN", "https://key@localhost/1")

        _reload()

        before_send = recorded_init[0]["before_send"]
        event = {
            "exception": {
                "values": [
                    {
                        "type": "RuntimeError",
                        "value": "CurrentThreadExecutor already quit or is broken",
                        "mechanism": {"type": "asgi", "handled": False},
                    }
                ]
            }
        }
        assert "tags" in before_send(event, {})

    def test_current_thread_executor_wrapped_in_chain_dropped(
        self, monkeypatch: pytest.MonkeyPatch, recorded_init: list[dict[str, Any]]
    ):
        # The RuntimeError may sit anywhere in the exception chain (here
        # values[0], with an outer wrapper at values[-1]) — the filter
        # checks every value's own stacktrace, unlike the sibling shield
        # filter which only inspects values[-1].
        monkeypatch.setenv("SENTRY_DSN", "https://key@localhost/1")

        _reload()

        before_send = recorded_init[0]["before_send"]
        event = {
            "exception": {
                "values": [
                    {
                        "type": "RuntimeError",
                        "value": "CurrentThreadExecutor already quit or is broken",
                        "mechanism": {"type": "asgi", "handled": False},
                        "stacktrace": {
                            "frames": [
                                {
                                    "function": "handle",
                                    "module": "django.core.handlers.asgi",
                                    "filename": "django/core/handlers/asgi.py",
                                },
                                {
                                    "function": "asend",
                                    "module": "django.dispatch.dispatcher",
                                    "filename": "django/dispatch/dispatcher.py",
                                },
                            ]
                        },
                    },
                    {
                        "type": "ExceptionGroup",
                        "value": "unhandled errors in a TaskGroup",
                        "mechanism": {"type": "asgi", "handled": False},
                    },
                ]
            }
        }
        assert before_send(event, {}) is None

    def test_app_version_tag_attached_to_transactions(
        self, monkeypatch: pytest.MonkeyPatch, recorded_init: list[dict[str, Any]]
    ):
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

    def test_report_noop_without_active_client(self, monkeypatch: pytest.MonkeyPatch):
        import sentry_sdk

        from server.core.q2_sentry import SentryErrorReporter

        assert sentry_sdk.get_client().is_active() is False  # test env: no DSN
        called = []

        def _capture(*args: Any, **kwargs: Any) -> None:
            called.append(args)

        monkeypatch.setattr(sentry_sdk, "capture_exception", _capture)

        try:
            raise RuntimeError("boom")
        except RuntimeError:
            SentryErrorReporter().report()

        assert called == []  # inert: SDK not active in dev/test/CI

    def test_report_captures_live_exception_when_active(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        import sentry_sdk

        from server.core.q2_sentry import SentryErrorReporter

        monkeypatch.setattr(
            sentry_sdk,
            "get_client",
            lambda: _ActiveClient(),
        )
        captured = []

        def _capture(*args: Any, **kwargs: Any) -> None:
            captured.append(args)

        monkeypatch.setattr(
            sentry_sdk,
            "capture_exception",
            _capture,
        )

        try:
            raise ValueError("task failed")
        except ValueError:
            SentryErrorReporter().report()

        # capture_exception() with no args must pick up the live
        # sys.exc_info() — this is the reporter's whole point.
        assert captured == [()]

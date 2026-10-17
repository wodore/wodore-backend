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
    def test_health_checks_never_traced(self, monkeypatch, recorded_init):
        monkeypatch.setenv("SENTRY_DSN", "https://key@localhost/1")

        _reload()

        sampler = recorded_init[0]["traces_sampler"]
        assert sampler({"transaction_context": {"name": "/health/complete/"}}) == 0.0

    def test_default_rate_applies_to_api_requests(self, monkeypatch, recorded_init):
        monkeypatch.setenv("SENTRY_DSN", "https://key@localhost/1")
        monkeypatch.delenv("SENTRY_TRACES_SAMPLE_RATE", raising=False)

        _reload()

        sampler = recorded_init[0]["traces_sampler"]
        assert sampler({"transaction_context": {"name": "/v1/huts/"}}) == 0.05

    def test_rate_configurable_and_zero_disables(self, monkeypatch, recorded_init):
        monkeypatch.setenv("SENTRY_DSN", "https://key@localhost/1")
        monkeypatch.setenv("SENTRY_TRACES_SAMPLE_RATE", "0.5")

        _reload()

        sampler = recorded_init[0]["traces_sampler"]
        assert sampler({"transaction_context": {"name": "/v1/huts/"}}) == 0.5

        monkeypatch.setenv("SENTRY_TRACES_SAMPLE_RATE", "0")
        _reload()
        sampler = recorded_init[1]["traces_sampler"]
        assert sampler({"transaction_context": {"name": "/v1/huts/"}}) == 0.0


class TestBeforeSend:
    def test_app_version_tag_attached(self, monkeypatch, recorded_init):
        from importlib.metadata import version

        monkeypatch.setenv("SENTRY_DSN", "https://key@localhost/1")

        _reload()

        before_send = recorded_init[0]["before_send"]
        event = before_send({}, {})
        assert event["tags"]["app_version"] == version("wodore-backend")

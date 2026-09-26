"""Tests for the OIDC feature flags (spec: optional-oidc).

Flag semantics under test (settings component loads before the environment
files):

- ``OIDC_ENABLED`` defaults to true in ALL environments (the built-in
  provider serves dev/test and production alike); explicit env vars win
- ``LOCAL_AUTH_ENABLED`` no longer exists (retired with the hand-rolled
  provider)
- production without a provider signing key aborts startup (fail-fast)
- production with ``ZITADEL_ROLLBACK_ENABLED=true`` but no Zitadel
  machine-user key aborts startup

Settings load in a subprocess with a controlled DJANGO_ENV; importing
settings performs no database access. The committed dev key (JSON JWK) is
injected via env where a production-style load must succeed.
"""

import json
import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.django_db


def _dev_key_json() -> str:
    """The resolved (dev/test committed) provider key as JSON for envs."""
    from django.conf import settings

    return json.dumps(settings.OIDC_PROVIDER_PRIVATE_JWK)


def _load_settings_env(env: str, extra: dict[str, str] | None = None) -> str:
    """Load Django settings in a subprocess with a given DJANGO_ENV.

    Returns combined stdout+stderr.
    """
    environ = {
        **os.environ,
        "DJANGO_ENV": env,
        "DJANGO_SETTINGS_MODULE": "server.settings",
    }
    if extra:
        environ.update(extra)
    result = subprocess.run(
        [sys.executable, "-c", _PRINT_FLAGS],
        capture_output=True,
        text=True,
        env=environ,
        timeout=120,
    )
    return result.stdout + result.stderr


_PRINT_FLAGS = (
    "import django; django.setup(); "
    "from django.conf import settings; "
    "print(f'OIDC_ENABLED={settings.OIDC_ENABLED}'); "
    "print(f'ROLLBACK={settings.ZITADEL_ROLLBACK_ENABLED}'); "
    "print(f'HAS_LOCAL_AUTH={hasattr(settings, \"LOCAL_AUTH_ENABLED\")}')"
)


class TestFlagDefaults:
    @pytest.mark.parametrize("env", ["development", "test"])
    def test_builtin_provider_on_everywhere(self, env):
        out = _load_settings_env(env)
        assert "OIDC_ENABLED=True" in out
        assert "HAS_LOCAL_AUTH=False" in out
        assert "Traceback" not in out

    def test_production_defaults(self):
        out = _load_settings_env(
            "production",
            extra={
                "LOCAL_AUTH_PRIVATE_KEY_JWK": _dev_key_json(),
                # Hermetic: CI does not carry the Zitadel machine-user key,
                # and the rollback fail-fast would abort the load.
                "ZITADEL_API_PRIVATE_KEY_JSON": '{"clientId":"x","keyId":"y","key":"z"}',
                "OIDC_ENABLED": "true",
            },
        )
        assert "OIDC_ENABLED=True" in out
        # Rollback defaults on outside dev/test until decommission.
        assert "ROLLBACK=True" in out
        assert "HAS_LOCAL_AUTH=False" in out
        assert "Traceback" not in out

    def test_explicit_disable_wins(self):
        out = _load_settings_env("development", extra={"OIDC_ENABLED": "false"})
        assert "OIDC_ENABLED=False" in out


class TestFailFast:
    def test_production_without_signing_key_aborts(self):
        out = _load_settings_env("production", extra={"LOCAL_AUTH_PRIVATE_KEY_JWK": ""})
        assert "ImproperlyConfigured" in out
        assert "LOCAL_AUTH_PRIVATE_KEY_JWK" in out

    def test_rollback_without_zitadel_key_aborts(self):
        out = _load_settings_env(
            "production",
            extra={
                "LOCAL_AUTH_PRIVATE_KEY_JWK": _dev_key_json(),
                "ZITADEL_API_PRIVATE_KEY_JSON": "",
            },
        )
        assert "ImproperlyConfigured" in out
        assert "ZITADEL" in out

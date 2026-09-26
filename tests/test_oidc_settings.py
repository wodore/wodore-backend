"""Tests for the auth provider switch (spec: optional-oidc).

Semantics under test (settings component loads before the environment
files):

- ``AUTH_PROVIDER`` defaults to ``builtin`` in development/test and
  ``zitadel`` in production/staging; explicit env vars always win
- ``AUTH_PROVIDER=builtin`` outside dev/test without a provider signing
  key aborts startup (fail-fast)
- ``AUTH_PROVIDER=zitadel`` with an unreachable provider aborts startup
  (discovery fail-fast, as before the migration)

Settings load in a subprocess with a controlled DJANGO_ENV; importing
settings performs no database access.
"""

import json
import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.django_db

_PRINT_FLAGS = (
    "import django; django.setup(); "
    "from django.conf import settings; "
    "print(f'AUTH_PROVIDER={settings.AUTH_PROVIDER}'); "
    "print(f'OIDC_ENABLED={settings.OIDC_ENABLED}'); "
    "print(f'ZITADEL_RP_ENABLED={settings.ZITADEL_RP_ENABLED}'); "
    "print(f'ROLLBACK={settings.ZITADEL_ROLLBACK_ENABLED}'); "
    "print(f'HAS_LOCAL_AUTH={hasattr(settings, \"LOCAL_AUTH_ENABLED\")}')"
)


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


class TestFlagDefaults:
    @pytest.mark.parametrize("env", ["development", "test"])
    def test_builtin_provider_by_default_in_dev(self, env):
        out = _load_settings_env(env)
        assert "AUTH_PROVIDER=builtin" in out
        assert "OIDC_ENABLED=True" in out
        assert "ZITADEL_RP_ENABLED=False" in out
        assert "HAS_LOCAL_AUTH=False" in out
        assert "Traceback" not in out

    def test_zitadel_stays_default_in_production(self):
        """Phase 1 keeps Zitadel as the production default; the flip to
        builtin is a later env change (AUTH_PROVIDER=builtin)."""
        out = _load_settings_env("production")
        assert "ImproperlyConfigured" in out  # no reachable provider configured
        assert "OIDC_OP_BASE_URL" in out

    def test_production_zitadel_mode_with_builtin_key_only(self):
        """Zitadel mode must not require the builtin provider key."""
        out = _load_settings_env(
            "production",
            extra={
                "AUTH_PROVIDER": "zitadel",
                "OIDC_OP_BASE_URL": "https://zitadel.invalid",
            },
        )
        assert "ImproperlyConfigured" in out  # discovery fail-fast, not key

    def test_builtin_in_production_requires_key(self):
        out = _load_settings_env("production", extra={"AUTH_PROVIDER": "builtin"})
        assert "ImproperlyConfigured" in out
        assert "LOCAL_AUTH_PRIVATE_KEY_JWK" in out

    def test_explicit_builtin_wins_in_production(self):
        out = _load_settings_env(
            "production",
            extra={
                "AUTH_PROVIDER": "builtin",
                "LOCAL_AUTH_PRIVATE_KEY_JWK": _dev_key_json(),
                "ZITADEL_API_PRIVATE_KEY_JSON": '{"clientId":"x","keyId":"y","key":"z"}',
            },
        )
        assert "AUTH_PROVIDER=builtin" in out
        assert "OIDC_ENABLED=True" in out
        assert "ZITADEL_RP_ENABLED=False" in out
        assert "ROLLBACK=True" in out
        assert "Traceback" not in out

    def test_invalid_provider_value_aborts(self):
        out = _load_settings_env(
            "development",
            extra={
                "AUTH_PROVIDER": "saml",
                "LOCAL_AUTH_PRIVATE_KEY_JWK": _dev_key_json(),
            },
        )
        assert "ImproperlyConfigured" in out
        assert "AUTH_PROVIDER" in out


class TestFailFast:
    def test_zitadel_mode_unreachable_provider_aborts(self):
        out = _load_settings_env(
            "development",
            extra={"AUTH_PROVIDER": "zitadel"},
        )
        assert "ImproperlyConfigured" in out
        assert "discovery" in out

    def test_rollback_without_zitadel_key_aborts(self):
        out = _load_settings_env(
            "production",
            extra={
                "AUTH_PROVIDER": "builtin",
                "LOCAL_AUTH_PRIVATE_KEY_JWK": _dev_key_json(),
                "ZITADEL_API_PRIVATE_KEY_JSON": "",
            },
        )
        assert "ImproperlyConfigured" in out
        assert "Zitadel" in out

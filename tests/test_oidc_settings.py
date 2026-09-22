"""Tests for the optional-OIDC feature flags (spec: optional-oidc).

Flag semantics under test (settings component loads before the environment
files, so defaults derive from DJANGO_ENV):

- development/test: OIDC disabled, local auth provider enabled (default)
- production/staging: OIDC enabled, local auth refused
- explicit env vars always win
- enabled-but-unreachable provider aborts startup (fail-fast)

Settings load in a subprocess with a controlled DJANGO_ENV; importing
settings performs no database access.
"""

import os
import subprocess
import sys

import pytest

from django.core.management import call_command
from django.core.management.base import CommandError

pytestmark = pytest.mark.django_db

_PRINT_FLAGS = (
    "import django; django.setup(); "
    "from django.conf import settings; "
    "print(f'OIDC_ENABLED={settings.OIDC_ENABLED}'); "
    "print(f'LOCAL_AUTH_ENABLED={settings.LOCAL_AUTH_ENABLED}')"
)


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
        timeout=90,
    )
    return result.stdout + result.stderr


class TestFlagDefaults:
    def test_dev_defaults_to_local_auth(self):
        out = _load_settings_env("development")
        assert "OIDC_ENABLED=False" in out
        assert "LOCAL_AUTH_ENABLED=True" in out

    def test_test_env_defaults_to_local_auth(self):
        out = _load_settings_env("test")
        assert "OIDC_ENABLED=False" in out
        assert "LOCAL_AUTH_ENABLED=True" in out


class TestFailFast:
    def test_enabled_but_unreachable_aborts(self):
        """Production default enables OIDC; the unreachable provider must abort."""
        out = _load_settings_env("production")
        assert (
            "OIDC is enabled but the discovery document could not be retrieved" in out
        )

    def test_explicit_oidc_enabled_override_in_test_env(self):
        """An explicit OIDC_ENABLED=true override must be honored (and then
        fail fast against the unreachable default provider)."""
        out = _load_settings_env("test", extra={"OIDC_ENABLED": "true"})
        assert (
            "OIDC is enabled but the discovery document could not be retrieved" in out
        )

    def test_production_refuses_local_auth(self):
        out = _load_settings_env("production", extra={"LOCAL_AUTH_ENABLED": "true"})
        assert "LOCAL_AUTH_ENABLED=true is only allowed" in out


class TestDisabledMode:
    def test_oidc_disabled_in_test_env(self, settings):
        assert settings.OIDC_ENABLED is False
        assert settings.LOCAL_AUTH_ENABLED is True

    def test_permission_backend_not_registered(self, settings):
        assert (
            "server.core.oidc_permission.PermissionBackend"
            not in settings.AUTHENTICATION_BACKENDS
        )
        assert (
            "django.contrib.auth.backends.ModelBackend"
            in settings.AUTHENTICATION_BACKENDS
        )

    def test_oidc_urls_not_mounted(self):
        from django.urls import Resolver404, resolve

        with pytest.raises(Resolver404):
            resolve("/oidc/authenticate/")

    def test_admin_login_is_classic_form(self, client):
        response = client.get("/admin/login/?next=/admin/")
        assert response.status_code == 200
        assert b"/oidc/authenticate" not in response.content

    def test_api_test_token_refuses(self):
        with pytest.raises(CommandError, match="OIDC is disabled"):
            call_command("api_test_token")

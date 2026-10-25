"""``resolve_setting`` — admin-managed overrides for Django URL settings.

``MARTIN_TILE_URL`` / ``IMAGOR_URL`` / ``BACKEND_DOMAIN`` are seeded as
registry rows (empty value + env fallback): the Django setting — itself
env/infisical-driven via decouple — keeps serving until an operator
stores a value in the admin. These tests pin that precedence.
"""

from __future__ import annotations

import importlib

import pytest

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from server.apps.basemaps.resolution import resolve_style
from server.apps.envvars.models import EnvVar
from server.apps.envvars.registry import CACHE_KEY, resolve_setting

#: A real seeded URL-origin name (also proves it passes the admin
#: allowlist validation — no SECRET/TOKEN/PASSWORD parts).
NAME = "IMAGOR_URL"


@pytest.fixture(autouse=True)
def _fresh_registry(request: pytest.FixtureRequest):
    """DB-backed tests start from an empty registry + dropped snapshot.

    No-DB tests (SimpleTestCase) skip the wipe — they exercise the
    registry-unavailable degradation path on purpose.
    """
    if not request.node.get_closest_marker("django_db"):
        yield
        return
    EnvVar.objects.all().delete()
    cache.delete(CACHE_KEY)
    yield
    cache.delete(CACHE_KEY)


def _row(
    name: str = NAME, value: str = "", is_active: bool = True, env_fallback: bool = True
) -> EnvVar:
    """Create/update one registry row (signals invalidate the snapshot)."""
    row, _ = EnvVar.objects.update_or_create(
        name=name,
        defaults={"value": value, "is_active": is_active, "env_fallback": env_fallback},
    )
    return row


@pytest.mark.django_db
class TestResolveSetting:
    def test_no_row_falls_back_to_setting(self):
        with override_settings(IMAGOR_URL="https://img.example.org"):
            assert resolve_setting("IMAGOR_URL") == "https://img.example.org"

    def test_stored_value_wins_over_setting(self):
        _row(value="https://img.cdn.example.org")
        with override_settings(IMAGOR_URL="https://img.example.org"):
            assert resolve_setting("IMAGOR_URL") == "https://img.cdn.example.org"

    def test_stray_env_export_never_beats_the_setting(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Decouple loads config onto the *setting*; a shell export of
        the same name must not leak past ``override_settings``."""
        monkeypatch.setenv(NAME, "https://stray-export.example")
        with override_settings(IMAGOR_URL="https://img.example.org"):
            assert resolve_setting("IMAGOR_URL") == "https://img.example.org"

    def test_pinned_empty_beats_setting(self):
        _row(value="", env_fallback=False)
        with override_settings(IMAGOR_URL="https://img.example.org"):
            assert resolve_setting("IMAGOR_URL") == ""

    def test_inactive_row_falls_back_to_setting(self):
        _row(value="https://img.cdn.example.org", is_active=False)
        with override_settings(IMAGOR_URL="https://img.example.org"):
            assert resolve_setting("IMAGOR_URL") == "https://img.example.org"

    def test_unknown_name_uses_default(self):
        assert resolve_setting("NOT_A_DJANGO_SETTING", "fallback") == "fallback"


@pytest.mark.django_db
class TestUrlOriginSeed:
    """Migration 0004 seeds the three URL-origin rows."""

    def test_seed_creates_empty_fallback_rows(self):
        """Empty + fallback rows keep today's behavior: the setting serves."""
        from django.apps import apps as global_apps

        migration = importlib.import_module(
            "server.apps.envvars.migrations.0004_seed_url_origins"
        )
        migration.seed(global_apps, None)
        for name, _description in migration.DEFAULTS:
            row = EnvVar.objects.get(name=name)
            assert row.value == ""
            assert row.env_fallback is True
            assert row.is_active is True
            with override_settings(**{name: "https://from-setting.example"}):
                assert resolve_setting(name) == "https://from-setting.example"
        migration.unseed(global_apps, None)
        assert not EnvVar.objects.filter(
            name__in=[name for name, _ in migration.DEFAULTS]
        ).exists()


class NoDatabaseDegradation(SimpleTestCase):
    """``resolve_setting`` works wherever the plain setting did.

    No-DB contexts (SimpleTestCase, early boot) must degrade to
    "registry off" — the Django setting serves — not raise. Pins the
    regression where ``resolve_style`` became DB-bound through the
    registry and broke no-DB callers.
    """

    @override_settings(MARTIN_TILE_URL="https://tiles.example.org")
    def test_registry_unavailable_falls_back_to_setting(self):
        self.assertEqual(
            resolve_setting("MARTIN_TILE_URL"), "https://tiles.example.org"
        )


@pytest.mark.django_db
class TestStyleResolutionUsesRegistry:
    def test_registry_value_flows_into_style_resolution(self):
        """End-to-end: a DB override changes the served tile origin."""
        _row(name="MARTIN_TILE_URL", value="https://tiles.cdn.example.org")
        style = {"sources": {"huts": {"tiles": ["{TILE_SERVER_URL}/huts/{z}/{x}/{y}"]}}}
        resolved = resolve_style(style, {})
        assert resolved["sources"]["huts"]["tiles"] == [
            "https://tiles.cdn.example.org/huts/{z}/{x}/{y}"
        ]

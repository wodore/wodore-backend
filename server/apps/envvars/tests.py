"""EnvVar registry tests — validation, precedence, invalidation."""

from __future__ import annotations

import pytest

from django.conf import settings
from django.core.exceptions import ValidationError

from server.apps.basemaps.resolution import build_env, missing_env_names, substitute_env
from server.apps.envvars.models import EnvVar
from server.apps.envvars.registry import CACHE_KEY, resolve, resolve_many, rows, usable

KEY = "WODORE_TEST_KEY"
#: One ``{{env:…}}`` token referencing KEY (plain concat — no f-string
#: brace escaping).
TOKEN = "{{env:" + KEY + "}}"


def _row(
    name: str = KEY, value: str = "", is_active: bool = True, env_fallback: bool = True
) -> EnvVar:
    """Create/update one registry row (signals invalidate the snapshot)."""
    row, _ = EnvVar.objects.update_or_create(
        name=name,
        defaults={"value": value, "is_active": is_active, "env_fallback": env_fallback},
    )
    return row


@pytest.fixture(autouse=True)
def _fresh_snapshot():
    """Every test starts from an empty registry + dropped snapshot."""
    from django.core.cache import cache

    EnvVar.objects.all().delete()  # incl. the migration-seeded maptiler row
    cache.delete(CACHE_KEY)
    yield
    cache.delete(CACHE_KEY)


@pytest.mark.django_db
class TestModelValidation:
    def test_rejects_bad_names(self):
        for name in ("WITH-DASH", "1STARTS_WITH_DIGIT", "", "HAS SPACE"):
            row = EnvVar(name=name)
            with pytest.raises(ValidationError):
                row.full_clean()

    def test_names_are_uppercased_on_save(self):
        """Lower/mixed case input is normalized, not rejected."""
        row = EnvVar.objects.create(name="wodore_test_key", description="x")
        assert row.name == "WODORE_TEST_KEY"
        row.refresh_from_db()
        assert row.name == "WODORE_TEST_KEY"

    def test_full_clean_normalizes_case(self):
        row = EnvVar(name="mapy_com_api_key")
        row.full_clean()
        assert row.name == "MAPY_COM_API_KEY"

    def test_rejects_server_secret_names(self):
        for name in (
            "SECRET_KEY",
            "DATABASE_URL",
            "INFISICAL_TOKEN",
            "SMTP_PASSWORD",
            "SIGNING_PRIVATE_KEY",
        ):
            row = EnvVar(name=name)
            with pytest.raises(ValidationError):
                row.full_clean()

    def test_accepts_operational_keys(self):
        for name in ("WODORE_MAPTILER_API_KEY", "MAPY_COM_API_KEY", "SOME_HOST"):
            EnvVar(name=name).full_clean()


@pytest.mark.django_db
class TestPrecedence:
    def test_unregistered_never_resolves(self, monkeypatch):
        monkeypatch.setenv(KEY, "from-env")
        assert resolve(KEY) is None
        assert build_env({KEY}) == {}

    def test_inactive_forbids_even_with_env(self, monkeypatch):
        monkeypatch.setenv(KEY, "from-env")
        _row(is_active=False, value="even-a-value")
        assert resolve(KEY) is None

    def test_stored_value_wins_over_env(self, monkeypatch):
        monkeypatch.setenv(KEY, "from-env")
        _row(value="from-admin")
        assert resolve(KEY) == "from-admin"

    def test_empty_with_falls_back_to_env_then_settings(self, monkeypatch):
        monkeypatch.delenv(KEY, raising=False)
        monkeypatch.setattr(settings, KEY, "", raising=False)
        _row()
        assert resolve(KEY) is None  # nothing to fall back to
        monkeypatch.setenv(KEY, "from-env")
        assert resolve(KEY) == "from-env"

    def test_pinned_empty_wins_over_env(self, monkeypatch):
        monkeypatch.setenv(KEY, "from-env")
        _row(env_fallback=False)
        assert resolve(KEY) == ""
        assert substitute_env(f"https://x/?key={TOKEN}") == "https://x/?key="


@pytest.mark.django_db
class TestUsableAndGating:
    def test_usable_matrix(self, monkeypatch):
        monkeypatch.delenv(KEY, raising=False)
        monkeypatch.setattr(settings, KEY, "", raising=False)
        _row()
        assert not usable(KEY)  # registered but unresolved
        monkeypatch.setenv(KEY, "k")
        assert usable(KEY)
        _row(value="v")
        assert usable(KEY)

    def test_empty_env_value_not_usable(self, monkeypatch):
        monkeypatch.setenv(KEY, "")
        _row()
        assert resolve(KEY) == ""
        assert not usable(KEY)  # blank env keys are accidents, not intent
        assert missing_env_names(TOKEN) == {KEY}

    def test_pinned_empty_is_usable(self, monkeypatch):
        monkeypatch.setenv(KEY, "ignored")
        _row(env_fallback=False)
        assert usable(KEY)
        assert missing_env_names(TOKEN) == set()

    def test_inactive_not_usable(self, monkeypatch):
        monkeypatch.setenv(KEY, "k")
        _row(is_active=False)
        assert not usable(KEY)


@pytest.mark.django_db
class TestMapSeedIntegration:
    """map_seed provisions the env-registry entries the catalog needs."""

    def test_creates_missing_entries(self):
        from django.core.management import call_command

        call_command("map_seed", verbosity=0)
        names = set(EnvVar.objects.values_list("name", flat=True))
        assert {"WODORE_MAPTILER_API_KEY", "MAPY_COM_API_KEY"} <= names
        maptiler = EnvVar.objects.get(name="WODORE_MAPTILER_API_KEY")
        assert maptiler.value == ""
        assert maptiler.env_fallback is True
        assert maptiler.is_active is True

    def test_never_overwrites_operator_values(self):
        from django.core.management import call_command

        _row("WODORE_MAPTILER_API_KEY", value="op-key", is_active=False)
        call_command("map_seed", verbosity=0)
        row = EnvVar.objects.get(name="WODORE_MAPTILER_API_KEY")
        assert row.value == "op-key"
        assert row.is_active is False


@pytest.mark.django_db
class TestSnapshotCache:
    def test_rows_cached_and_invalidated_on_save(self):
        from django.core.cache import cache

        _row(value="v1")
        assert rows()[KEY] == ("v1", True, True)
        cache.set(CACHE_KEY, {KEY: ("stale", True, True)}, 60)
        assert rows()[KEY] == ("stale", True, True)  # memo window
        _row(value="v2")  # signal invalidates
        assert rows()[KEY] == ("v2", True, True)

    def test_resolve_many_resolves_only_given_names(self, monkeypatch):
        monkeypatch.setenv(KEY, "v")
        _row()
        _row("WODORE_OTHER_KEY", value="other")
        assert resolve_many({KEY}) == {KEY: "v"}

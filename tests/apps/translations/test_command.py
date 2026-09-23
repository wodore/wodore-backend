"""Tests for the `update_translations` management command."""

import pytest

from tests.apps.translations.conftest import FakeTranslationClient
from tests.factories.huts import HutFactory

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

pytestmark = pytest.mark.django_db

COMMAND_MODULE = "server.apps.translations.management.commands.update_translations"

EMPTY_API_SETTINGS = dict(
    TRANSLATION_API_BASE_URL="",
    TRANSLATION_API_KEY="",
    TRANSLATION_MODEL="",
)


def patch_client(monkeypatch, fake):
    monkeypatch.setattr(f"{COMMAND_MODULE}.TranslationClient", lambda: fake)


def test_command_translates_single_hut(monkeypatch, capsys):
    hut = HutFactory(name="Bergghütte")
    fake = FakeTranslationClient()
    patch_client(monkeypatch, fake)

    call_command("update_translations", "--hut", hut.slug)

    hut.refresh_from_db()
    assert hut.i18n["name_fr"] == "Bergghütte-fr"
    assert hut.i18n["name_en"] == "Bergghütte-en"
    assert fake.calls[0]["source_lang"] == "de"
    output = capsys.readouterr().out
    assert "translated" in output
    assert "1 instance(s) processed" in output


def test_command_respects_languages_filter(monkeypatch):
    hut = HutFactory(name="Bergghütte")
    fake = FakeTranslationClient()
    patch_client(monkeypatch, fake)

    call_command("update_translations", "--hut", hut.slug, "--languages", "fr")

    hut.refresh_from_db()
    assert hut.i18n["name_fr"] == "Bergghütte-fr"
    assert "name_en" not in (hut.i18n or {})
    assert fake.calls[0]["target_langs"] == ["fr"]


def test_command_dry_run_without_config(capsys):
    hut = HutFactory(name="Bergghütte")
    with override_settings(**EMPTY_API_SETTINGS):
        call_command("update_translations", "--hut", hut.slug, "--dry-run")

    hut.refresh_from_db()
    assert not hut.i18n  # nothing saved
    output = capsys.readouterr().out
    assert "would translate" in output


def test_command_unconfigured_api_raises():
    hut = HutFactory(name="Bergghütte")
    with override_settings(**EMPTY_API_SETTINGS):
        with pytest.raises(CommandError, match="Translation API"):
            call_command("update_translations", "--hut", hut.slug)


def test_command_rejects_unknown_language():
    with pytest.raises(CommandError, match="Unknown language"):
        call_command("update_translations", "--hut", "x", "--languages", "xx,de")


def test_command_requires_selector():
    with pytest.raises(CommandError, match="Nothing to do"):
        call_command("update_translations")


def test_command_all_requires_model():
    with pytest.raises(CommandError, match="--all requires --model"):
        call_command("update_translations", "--all")


def test_command_unknown_slug_raises():
    with pytest.raises(CommandError, match="not found"):
        call_command("update_translations", "--hut", "does-not-exist")


def test_command_limit_processes_subset(monkeypatch):
    HutFactory.create_batch(3, name="Hütte")
    fake = FakeTranslationClient()
    patch_client(monkeypatch, fake)

    call_command("update_translations", "--model", "hut", "--all", "--limit", 2)

    assert len(fake.calls) == 2

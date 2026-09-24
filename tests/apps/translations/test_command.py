"""Tests for the `update_translations` management command."""

import pytest

from tests.apps.translations.conftest import FakeTranslationClient
from tests.factories.huts import HutFactory

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from server.apps.huts.models import Hut

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


# --- assess_descriptions command ---

ASSESS_MODULE = "server.apps.translations.management.commands.assess_descriptions"


def patch_assess_client(monkeypatch, fake):
    monkeypatch.setattr(f"{ASSESS_MODULE}.TranslationClient", lambda: fake)


def _done_hut(**kwargs):
    hut = HutFactory(**kwargs)
    Hut.objects.filter(pk=hut.pk).update(review_status="done")
    hut.refresh_from_db()
    return hut


def test_assess_command_moves_done_hut_to_rework(monkeypatch, capsys):
    hut = _done_hut(name="Redaktionshütte", description="Kurzer Text.")
    fake = FakeTranslationClient(assess_result={"score": 4, "summary": "Too thin."})
    patch_assess_client(monkeypatch, fake)

    call_command("assess_descriptions", "--hut", hut.slug)

    hut.refresh_from_db()
    assert hut.description_quality == 4
    assert hut.review_status == "rework"
    assert "[LLM" in hut.review_comment
    output = capsys.readouterr().out
    assert "4/10" in output
    assert "rework" in output


def test_assess_command_keeps_queued_huts(monkeypatch):
    hut = HutFactory(name="Wartehütte", description="Text.")  # default: review
    fake = FakeTranslationClient(assess_result={"score": 3, "summary": "Bad."})
    patch_assess_client(monkeypatch, fake)

    call_command("assess_descriptions", "--hut", hut.slug)

    hut.refresh_from_db()
    assert hut.description_quality == 3
    assert hut.review_status == "review"  # untouched


def test_assess_command_defaults_to_unscored(monkeypatch):
    scored = _done_hut(name="Fertig3", description="Text.")
    Hut.objects.filter(pk=scored.pk).update(description_quality=8)
    fresh = _done_hut(name="Neu3", description="Anderer Text.")
    fake = FakeTranslationClient()
    patch_assess_client(monkeypatch, fake)

    call_command("assess_descriptions", "--model", "hut", "--all")

    assert len(fake.calls) == 1
    fresh.refresh_from_db()
    assert fresh.description_quality == 7


def test_assess_command_rescore(monkeypatch):
    hut = _done_hut(name="Rescorehütte", description="Text.")
    Hut.objects.filter(pk=hut.pk).update(description_quality=3)
    fake = FakeTranslationClient()
    patch_assess_client(monkeypatch, fake)

    call_command("assess_descriptions", "--hut", hut.slug, "--rescore")

    hut.refresh_from_db()
    assert hut.description_quality == 7


def test_assess_command_rework_below_override(monkeypatch):
    hut = _done_hut(name="Grenzfallhütte", description="Text.")
    fake = FakeTranslationClient(assess_result={"score": 7, "summary": "Gut."})
    patch_assess_client(monkeypatch, fake)

    call_command("assess_descriptions", "--hut", hut.slug, "--rework-below", "8")

    hut.refresh_from_db()
    assert hut.review_status == "rework"


def test_assess_command_limit(monkeypatch):
    # Explicit slugs (not --all): the session seed data adds huts to the
    # test DB, and --all processes them first.
    hut_a = HutFactory(name="Limithütte A", description="Text.")
    hut_b = HutFactory(name="Limithütte B", description="Text.")
    hut_c = HutFactory(name="Limithütte C", description="Text.")
    fake = FakeTranslationClient()
    patch_assess_client(monkeypatch, fake)

    call_command(
        "assess_descriptions",
        "--hut",
        hut_a.slug,
        "--hut",
        hut_b.slug,
        "--hut",
        hut_c.slug,
        "--limit",
        "2",
    )

    assert len(fake.calls) == 2


def test_assess_command_errors():
    with pytest.raises(CommandError, match="Nothing to do"):
        call_command("assess_descriptions")
    with pytest.raises(CommandError, match="not found"):
        call_command("assess_descriptions", "--hut", "does-not-exist")


def test_assess_command_unconfigured():
    hut = HutFactory(name="Ohnekonfighütte", description="Text.")
    with override_settings(**EMPTY_API_SETTINGS):
        with pytest.raises(CommandError, match="Translation API"):
            call_command("assess_descriptions", "--hut", hut.slug)


def test_assess_command_geoplace_selector(monkeypatch, capsys):
    from tests.factories.geometries import GeoPlaceFactory

    from server.apps.geometries.models import GeoPlace

    place = GeoPlaceFactory(name="Bewertungsort", description="Ein Ort.")
    GeoPlace.objects.filter(pk=place.pk).update(review_status="done")
    fake = FakeTranslationClient(assess_result={"score": 4, "summary": "Too thin."})
    patch_assess_client(monkeypatch, fake)

    call_command("assess_descriptions", "--geoplace", place.slug)

    place.refresh_from_db()
    assert place.description_quality == 4
    assert place.review_status == "rework"
    output = capsys.readouterr().out
    assert "4/10" in output
    assert "rework" in output


def test_assess_command_all_requires_model():
    with pytest.raises(CommandError, match="--all requires --model"):
        call_command("assess_descriptions", "--all")


def test_assess_command_unknown_geoplace():
    with pytest.raises(CommandError, match="not found"):
        call_command("assess_descriptions", "--geoplace", "does-not-exist")


def test_assess_command_rejects_cross_model_selectors():
    # Cross combos would silently widen to a full-model run (e.g. all
    # unscored huts); they are rejected before any API call.
    with pytest.raises(CommandError, match="cannot be combined with --geoplace"):
        call_command("assess_descriptions", "--model", "hut", "--geoplace", "zermatt")
    with pytest.raises(CommandError, match="cannot be combined with --hut"):
        call_command("assess_descriptions", "--model", "geoplace", "--hut", "some-hut")
    with pytest.raises(CommandError, match="cannot be mixed"):
        call_command("assess_descriptions", "--hut", "a", "--geoplace", "b")

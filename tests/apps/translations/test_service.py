"""Tests for server.apps.translations.service (translate_instance)."""

import pytest

from tests.apps.translations.conftest import FakeTranslationClient
from tests.factories.geometries import GeoPlaceFactory
from tests.factories.huts import HutFactory

from server.apps.geometries.models import GeoPlace
from server.apps.huts.models import Hut
from server.apps.translations.service import translate_instance

pytestmark = pytest.mark.django_db


def _update_hut(hut: Hut, **fields) -> Hut:
    """Update columns and return a DB-loaded instance (from_db sets _orig_*
    attributes that Hut.save() relies on; refresh_from_db does not)."""
    Hut.objects.filter(pk=hut.pk).update(**fields)
    return Hut.objects.get(pk=hut.pk)


def test_fills_only_empty_fields_and_keeps_existing():
    hut = _update_hut(
        HutFactory(name="Testhütte", description="Schöne Hütte"),
        i18n={"name_fr": "Cabane existante"},
    )
    fake = FakeTranslationClient()
    stats = translate_instance(hut, languages=["fr"], client=fake)

    assert stats["translated"] == {"fr": ["description"]}
    assert ("fr", "name") in stats["skipped_existing"]
    assert "note" in stats["skipped_no_source"]
    # Only fields with at least one missing translation are sent to the API
    # (name_fr already exists, so name is not part of the payload).
    assert fake.calls[0]["texts"] == {"description": "Schöne Hütte"}
    assert fake.calls[0]["source_lang"] == "de"

    hut.refresh_from_db()
    assert hut.i18n["name_fr"] == "Cabane existante"  # untouched
    assert hut.i18n["description_fr"] == "Schöne Hütte-fr"
    assert hut.description == "Schöne Hütte"  # base column untouched


def test_translates_from_main_language_into_default_column():
    hut = _update_hut(
        HutFactory(name="Platzhalter"),
        main_language="fr",
        name="",
        description="",
        i18n={"name_fr": "Cabane Mont Rose", "description_fr": "Belle cabane"},
    )
    fake = FakeTranslationClient()
    stats = translate_instance(hut, languages=["de", "en"], client=fake)

    assert stats["source_lang"] == "fr"
    assert fake.calls[0]["source_lang"] == "fr"
    hut.refresh_from_db()
    # de is the default language: translations land in the base columns.
    assert hut.name == "Cabane Mont Rose-de"
    assert hut.description == "Belle cabane-de"
    # source language untouched, en goes into i18n.
    assert hut.i18n["name_fr"] == "Cabane Mont Rose"
    assert hut.i18n["name_en"] == "Cabane Mont Rose-en"


def test_overwrite_replaces_existing_translations():
    hut = _update_hut(
        HutFactory(name="Testhütte"),
        i18n={"name_fr": "Cabane existante"},
    )
    translate_instance(
        hut, languages=["fr"], overwrite=True, client=FakeTranslationClient()
    )
    hut.refresh_from_db()
    assert hut.i18n["name_fr"] == "Testhütte-fr"


def test_dry_run_reports_plan_without_api_or_save():
    hut = HutFactory(name="Testhütte")
    fake = FakeTranslationClient()
    stats = translate_instance(hut, languages=["fr"], dry_run=True, client=fake)

    assert fake.calls == []  # no API call
    assert stats["translated"] == {"fr": ["name"]}
    assert stats["saved"] is False
    hut.refresh_from_db()
    assert not hut.i18n


def test_dry_run_works_without_client_and_config():
    hut = HutFactory(name="Testhütte")
    stats = translate_instance(hut, languages=["fr"], dry_run=True)
    assert stats["translated"] == {"fr": ["name"]}
    hut.refresh_from_db()
    assert not hut.i18n


def test_overlong_translation_is_skipped():
    hut = HutFactory(name="Testhütte")
    long_text = "x" * 150  # name is limited to 100 chars
    fake = FakeTranslationClient(result={"fr": {"name": long_text}})
    stats = translate_instance(hut, languages=["fr"], client=fake)
    assert stats["translated"] == {}
    assert stats["too_long"] == [("fr", "name", 150)]
    hut.refresh_from_db()
    assert not hut.i18n


def test_nothing_to_do_skips_api():
    hut = _update_hut(
        HutFactory(name="Testhütte"),
        i18n={"name_fr": "Cabane", "name_en": "Hut", "name_it": "Rifugio"},
    )
    fake = FakeTranslationClient()
    stats = translate_instance(hut, languages=["fr", "en", "it"], client=fake)
    assert fake.calls == []
    assert stats["saved"] is False
    assert stats["skipped_existing"]


def test_geoplace_translation_does_not_mark_modified():
    place = GeoPlaceFactory(name="Testplace")
    stats = translate_instance(place, languages=["en"], client=FakeTranslationClient())
    assert stats["saved"] is True
    place_db = GeoPlace.objects.get(pk=place.pk)
    assert place_db.i18n["name_en"] == "Testplace-en"
    assert place_db.is_modified is False


def test_main_language_drives_fallback_chain():
    """A French-main-language hut resolves name_i18n from French."""
    hut = _update_hut(
        HutFactory(name="Platzhalter"),
        main_language="fr",
        name="",
        i18n={"name_fr": "Cabane Mont Rose"},
    )
    assert hut.name_i18n == "Cabane Mont Rose"

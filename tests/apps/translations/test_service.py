"""Tests for server.apps.translations.service (translate_instance)."""

import pytest

from tests.apps.translations.conftest import FakeTranslationClient
from tests.factories.geometries import GeoPlaceFactory
from tests.factories.huts import HutFactory

from server.apps.geometries.models import GeoPlace
from server.apps.huts.models import Hut
from server.apps.translations.llm import TranslationError
from server.apps.translations.service import (
    assess_instance,
    store_quality,
    translate_instance,
)

pytestmark = pytest.mark.django_db


def _update_hut(hut: Hut, **fields) -> Hut:
    """Update columns and return a DB-loaded instance (from_db sets _orig_*
    attributes that Hut.save() relies on; refresh_from_db does not)."""
    Hut.objects.filter(pk=hut.pk).update(**fields)
    return Hut.objects.get(pk=hut.pk)


def _refetch(hut: Hut) -> Hut:
    """Return a DB-loaded copy of a factory-built hut (see _update_hut)."""
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


# --- Quality assessment (store_quality / assess_instance / piggyback) ---


def test_store_quality_moves_done_to_rework():
    hut = _update_hut(
        HutFactory(name="Fertighütte", description="Alles drin."),
        review_status="done",
        review_comment="Human note.",
    )
    touched = store_quality(hut, 4, "Too thin: no access info.")
    assert "review_status" in touched
    hut.save(update_fields=touched)
    hut.refresh_from_db()
    assert hut.description_quality == 4
    assert hut.description_quality_at is not None
    assert hut.review_status == "rework"
    assert hut.review_comment.startswith("Human note.")
    assert "quality 4/10]" in hut.review_comment


def test_store_quality_keeps_queued_statuses():
    for status in ("new", "review", "reject"):
        hut = _update_hut(HutFactory(name=f"Hütte-{status}"), review_status=status)
        touched = store_quality(hut, 2, "Unusable.")
        assert "review_status" not in touched
        assert hut.review_status == status


def test_store_quality_replaces_own_block_only():
    hut = _update_hut(
        HutFactory(name="Kommentarthütte"),
        review_comment="Human note.\n[LLM 2026-01-01 · quality 3/10] Old block.",
    )
    store_quality(hut, 8, "Much better now.")
    assert "Human note." in hut.review_comment
    assert "quality 3/10" not in hut.review_comment
    assert "quality 8/10" in hut.review_comment


def test_store_quality_rejects_invalid_score():
    hut = HutFactory(name="Badhütte")
    with pytest.raises(TranslationError, match="Invalid quality score"):
        store_quality(hut, 11, "x")


def test_store_quality_custom_threshold():
    hut = _update_hut(HutFactory(name="Grenzhütte"), review_status="done")
    touched = store_quality(hut, 7, "Good.", rework_below=8)
    assert "review_status" in touched
    assert hut.review_status == "rework"


def test_assess_instance_stores_and_reports():
    hut = _refetch(
        HutFactory(name="Bewertungshütte", description="Schöne, grosse Hütte.")
    )
    fake = FakeTranslationClient(assess_result={"score": 8, "summary": "Gut."})
    stats = assess_instance(hut, client=fake)
    assert stats == {"score": 8, "summary": "Gut.", "rework": False}
    hut.refresh_from_db()
    assert hut.description_quality == 8
    assert fake.calls[0]["assess"] == "Schöne, grosse Hütte."


def test_assess_instance_skips_empty_scored_unsupported():
    empty = HutFactory(name="Leerhütte", description="")
    assert assess_instance(empty, client=FakeTranslationClient()) == {
        "skipped": "empty"
    }
    scored = _update_hut(
        HutFactory(name="Fertig", description="Text."), description_quality=7
    )
    assert assess_instance(scored, client=FakeTranslationClient()) == {
        "skipped": "scored"
    }
    # GeoPlace now has quality fields (parity): without a description it
    # skips as "empty" instead of "unsupported".
    place = GeoPlaceFactory(name="Nirgendshaus")
    assert assess_instance(place, client=FakeTranslationClient()) == {
        "skipped": "empty"
    }
    # Models without quality fields still skip as "unsupported".
    from types import SimpleNamespace

    assert assess_instance(SimpleNamespace(), client=FakeTranslationClient()) == {
        "skipped": "unsupported"
    }


def test_assess_instance_rescore_overrides():
    scored = _update_hut(
        HutFactory(name="Neu bewertet", description="Text."), description_quality=2
    )
    fake = FakeTranslationClient(assess_result={"score": 5, "summary": "Mittel."})
    stats = assess_instance(scored, rescore=True, client=fake)
    assert stats["score"] == 5
    scored.refresh_from_db()
    assert scored.description_quality == 5


def test_translate_piggyback_stores_quality():
    hut = _refetch(HutFactory(name="Beihütte", description="Schöne Hütte am See."))
    fake = FakeTranslationClient(quality={"score": 6, "summary": "Basics."})
    stats = translate_instance(hut, languages=["fr"], client=fake)
    assert fake.calls[0]["assess_source"] is True
    assert stats["quality"] == {"score": 6, "summary": "Basics."}
    hut.refresh_from_db()
    assert hut.description_quality == 6
    assert hut.i18n["name_fr"] == "Beihütte-fr"  # translations still applied


def test_translate_piggyback_skipped_when_scored():
    hut = _update_hut(
        HutFactory(name="Fertig2", description="Text."), description_quality=7
    )
    fake = FakeTranslationClient()
    translate_instance(hut, languages=["fr"], client=fake)
    assert fake.calls[0]["assess_source"] is False
    hut.refresh_from_db()
    assert hut.description_quality == 7


def test_translate_piggyback_fires_for_geoplace():
    """GeoPlace parity: unscored description is assessed during translation."""
    place = GeoPlaceFactory(name="Beschriebener Ort", description="Ein schöner Ort.")
    place = GeoPlace.objects.get(pk=place.pk)
    fake = FakeTranslationClient(quality={"score": 6, "summary": "Basics."})
    stats = translate_instance(place, languages=["en"], client=fake)
    assert fake.calls[0]["assess_source"] is True
    assert stats["quality"] == {"score": 6, "summary": "Basics."}
    place.refresh_from_db()
    assert place.description_quality == 6
    assert place.i18n["name_en"]


def test_store_quality_moves_done_geoplace_to_rework():
    place = GeoPlaceFactory(name="Fertiger Ort", description="Schöner Ort.")
    GeoPlace.objects.filter(pk=place.pk).update(review_status="done")
    place = GeoPlace.objects.get(pk=place.pk)
    touched = store_quality(place, 4, "Too thin.")
    assert "review_status" in touched
    assert place.review_status == "rework"
    assert place.description_quality == 4
    assert "[LLM" in place.review_comment


def test_store_quality_keeps_queued_geoplace():
    place = GeoPlaceFactory(name="Neuer Ort", description="Text.")
    touched = store_quality(place, 3, "Thin.")
    assert "review_status" not in touched
    assert place.review_status == "new"


def test_translate_piggyback_skipped_when_scored_geoplace():
    place = GeoPlaceFactory(name="Bewerteter Ort", description="Ein Ort.")
    GeoPlace.objects.filter(pk=place.pk).update(description_quality=7)
    place = GeoPlace.objects.get(pk=place.pk)
    fake = FakeTranslationClient()
    translate_instance(place, languages=["en"], client=fake)
    assert fake.calls[0]["assess_source"] is False
    place.refresh_from_db()
    assert place.description_quality == 7


def test_description_quality_check_constraint():
    import pytest as _pytest

    from django.db import IntegrityError, transaction

    hut = HutFactory(name="Constrainthütte")
    with _pytest.raises(IntegrityError):
        with transaction.atomic():
            Hut.objects.filter(pk=hut.pk).update(description_quality=11)
    # NULL stays allowed.
    hut.refresh_from_db()
    assert hut.description_quality is None

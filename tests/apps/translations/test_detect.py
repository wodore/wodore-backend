"""Tests for server.apps.translations.detect."""

from server.apps.translations import detect_main_language


def test_detect_main_language_prefers_configured_order():
    assert detect_main_language({"fr": "Cabane", "de": "Hütte"}) == "de"
    # de/en missing -> next in LANGUAGE_CODES order (de, en, fr, it)
    assert detect_main_language({"fr": "Cabane", "it": "Rifugio"}) == "fr"
    assert detect_main_language({"it": "Rifugio", "en": "Hut"}) == "en"


def test_detect_main_language_ignores_empty_values():
    assert detect_main_language({"de": "", "fr": None, "en": "Hut"}) == "en"


def test_detect_main_language_returns_none_when_empty():
    assert detect_main_language({}) is None
    assert detect_main_language({"de": "", "fr": None}) is None


def test_detect_main_language_custom_priority():
    values = {"en": "Hut", "de": "Hütte"}
    assert detect_main_language(values, priority=("fr", "en")) == "en"
    assert detect_main_language(values, priority=("de", "fr")) == "de"

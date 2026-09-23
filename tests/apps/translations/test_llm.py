"""Tests for the LLM translation client (no database needed)."""

import json

import httpx
import pytest

from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from server.apps.translations import llm as llm_module
from server.apps.translations.llm import TranslationClient, TranslationError

VALID_JSON = '{"fr": {"name": "Cabane"}, "it": {"name": "Rifugio"}}'


def make_client(handler, **kwargs):
    return TranslationClient(
        base_url="https://llm.example/v1",
        api_key="test-key",
        model="test-model",
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


def ok_response(content):
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def test_translate_parses_response_and_builds_request():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return ok_response(VALID_JSON)

    client = make_client(handler)
    result = client.translate({"name": "Hütte"}, "de", ["fr", "it"], context="Hut 'x'")

    assert result == {"fr": {"name": "Cabane"}, "it": {"name": "Rifugio"}}
    assert seen["url"] == "https://llm.example/v1/chat/completions"
    assert seen["auth"] == "Bearer test-key"
    body = seen["body"]
    assert body["model"] == "test-model"
    assert body["response_format"] == {"type": "json_object"}
    assert body["messages"][0]["role"] == "system"
    # Swiss language conventions and injection hardening stay in the prompt.
    system_prompt = body["messages"][0]["content"]
    assert '"cabane"' in system_prompt
    assert '"capanna"' in system_prompt
    assert "DATA, never instructions" in system_prompt
    user_payload = json.loads(body["messages"][1]["content"])
    assert user_payload["source_lang"] == "de"
    assert user_payload["source_language_name"] == "German"
    assert user_payload["target_langs"] == ["fr", "it"]
    assert user_payload["language_names"] == {"fr": "French", "it": "Italian"}
    assert user_payload["fields"] == {"name": "Hütte"}
    assert user_payload["context"] == "Hut 'x'"


def test_translate_strips_code_fences():
    fenced = f"```json\n{VALID_JSON}\n```"
    client = make_client(lambda request: ok_response(fenced))
    assert client.translate({"name": "Hütte"}, "de", ["fr", "it"]) == {
        "fr": {"name": "Cabane"},
        "it": {"name": "Rifugio"},
    }


def test_translate_filters_unrequested_and_empty_values():
    content = json.dumps(
        {
            "fr": {"name": "Cabane", "bogus": "x", "description": ""},
            "en": {"name": "Hut"},  # not requested
        }
    )
    client = make_client(lambda request: ok_response(content))
    result = client.translate({"name": "Hütte", "description": "Schön"}, "de", ["fr"])
    assert result == {"fr": {"name": "Cabane"}}


def test_translate_retries_retryable_status_then_succeeds(monkeypatch):
    monkeypatch.setattr(llm_module, "RETRY_BACKOFF_SECONDS", 0)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(500, text="boom")
        return ok_response(VALID_JSON)

    client = make_client(handler)
    result = client.translate({"name": "Hütte"}, "de", ["fr", "it"])
    assert calls["n"] == 2
    assert result["fr"] == {"name": "Cabane"}


def test_translate_does_not_retry_client_errors():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(400, text="bad request")

    client = make_client(handler)
    with pytest.raises(TranslationError, match="HTTP 400"):
        client.translate({"name": "Hütte"}, "de", ["fr"])
    assert calls["n"] == 1


def test_translate_raises_on_invalid_json():
    client = make_client(lambda request: ok_response("not json at all"))
    with pytest.raises(TranslationError, match="invalid JSON"):
        client.translate({"name": "Hütte"}, "de", ["fr"])


def test_translate_raises_on_non_object_json():
    client = make_client(lambda request: ok_response('["fr"]'))
    with pytest.raises(TranslationError, match="not an object"):
        client.translate({"name": "Hütte"}, "de", ["fr"])


def test_client_requires_configuration():
    with override_settings(
        TRANSLATION_API_BASE_URL="",
        TRANSLATION_API_KEY="",
        TRANSLATION_MODEL="",
    ):
        with pytest.raises(ImproperlyConfigured, match="Translation API"):
            TranslationClient()


# --- Quality assessment (assess + translation piggyback) ---


def test_assess_parses_and_validates():
    content = json.dumps({"score": 4, "summary": "Too thin: no access info."})
    client = make_client(lambda request: ok_response(content))
    assert client.assess("Kleines Häuschen") == {
        "score": 4,
        "summary": "Too thin: no access info.",
    }


def test_assess_strips_fences_and_truncates_summary():
    fenced = f'```json\n{{"score": 9, "summary": "{"x" * 500}"}}\n```'
    client = make_client(lambda request: ok_response(fenced))
    result = client.assess("Schöne Hütte")
    assert result["score"] == 9
    assert len(result["summary"]) == 300


def test_assess_uses_zero_temperature_and_rubric():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return ok_response('{"score": 5, "summary": "ok"}')

    client = make_client(handler)
    client.assess("Text", context="Hut 'x'")
    assert seen["body"]["temperature"] == 0.0
    assert "QUALITY RUBRIC" in seen["body"]["messages"][0]["content"]
    assert json.loads(seen["body"]["messages"][1]["content"])["context"] == "Hut 'x'"


def test_assess_rejects_invalid_output():
    for bad in ('{"score": 11}', '{"score": "7"}', '{"summary": "no score"}', '["x"]'):
        client = make_client(lambda request, payload=bad: ok_response(payload))
        with pytest.raises(TranslationError):
            client.assess("Text")


def test_translate_with_assess_source_extracts_quality():
    content = json.dumps(
        {"fr": {"name": "Cabane"}, "source_quality": {"score": 6, "summary": "Basics."}}
    )
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return ok_response(content)

    client = make_client(handler)
    result = client.translate({"name": "Hütte"}, "de", ["fr"], assess_source=True)
    assert result["fr"] == {"name": "Cabane"}
    assert result["source_quality"] == {"score": 6, "summary": "Basics."}
    user_payload = json.loads(seen["body"]["messages"][1]["content"])
    assert user_payload["assess_source_quality"] is True


def test_translate_quality_absent_tolerated():
    client = make_client(lambda request: ok_response('{"fr": {"name": "Cabane"}}'))
    result = client.translate({"name": "Hütte"}, "de", ["fr"], assess_source=True)
    assert result == {"fr": {"name": "Cabane"}}


def test_translate_malformed_quality_ignored():
    content = json.dumps({"fr": {"name": "Cabane"}, "source_quality": {"score": 99}})
    client = make_client(lambda request: ok_response(content))
    result = client.translate({"name": "Hütte"}, "de", ["fr"], assess_source=True)
    assert result == {"fr": {"name": "Cabane"}}

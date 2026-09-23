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
    user_payload = json.loads(body["messages"][1]["content"])
    assert user_payload["source_lang"] == "de"
    assert user_payload["target_langs"] == ["fr", "it"]
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

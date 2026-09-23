"""LLM translation client for any OpenAI-compatible chat-completions API.

Configured via environment (Infisical):

- ``TRANSLATION_API_BASE_URL`` — e.g. ``https://api.z.ai/api/paas/v4`` (z.ai
  *general* API), ``https://api.openai.com/v1`` or a local server
  (Ollama/LM Studio: ``http://localhost:11434/v1``).
- ``TRANSLATION_API_KEY`` — API key of that endpoint.
- ``TRANSLATION_MODEL`` — model name, e.g. ``glm-4.6-flash``.
- ``TRANSLATION_API_TIMEOUT`` — request timeout in seconds (default 120).

Note: the z.ai *GLM Coding Plan* endpoint/key must NOT be used here. Its
terms restrict usage to supported coding tools; scripted/SDK usage may be
throttled. Use the pay-as-you-go general API instead.
"""

import json
import time
import typing as t

import httpx

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

RETRIES = 3
RETRY_BACKOFF_SECONDS = 2.0
RETRY_STATUS_CODES = frozenset({408, 409, 429, 500, 502, 503, 504})

_SYSTEM_PROMPT = (
    "You are a professional translator for a multilingual Swiss alpine "
    "platform about huts, mountain places and outdoor tourism.\n"
    "Translate the given fields from the source language into every requested "
    "target language.\n"
    "Rules:\n"
    "- Translate the meaning faithfully and keep the original tone.\n"
    "- Use customary local names for mountains, places and huts in the target "
    "language when they exist, otherwise keep proper nouns unchanged.\n"
    "- Do not add, remove or interpret information.\n"
    "- Preserve line breaks and markup (HTML/Markdown) exactly.\n"
    "- Keep numbers, units and their formatting unchanged.\n"
    '- Return ONLY a JSON object of the form {"<lang>": {"<field>": '
    '"<translation>"}} containing every requested language and field. '
    "No prose, no code fences.\n"
    '- If a field cannot be translated, return "" for it.'
)


class TranslationError(RuntimeError):
    """Raised when the translation API fails or returns unusable output."""


class TranslationClient:
    """Minimal OpenAI chat-completions client for field translations."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = (base_url or settings.TRANSLATION_API_BASE_URL or "").rstrip(
            "/"
        )
        self.api_key = api_key or settings.TRANSLATION_API_KEY or ""
        self.model = model or settings.TRANSLATION_MODEL or ""
        raw_timeout = (
            timeout if timeout is not None else settings.TRANSLATION_API_TIMEOUT
        )
        try:
            self.timeout = float(raw_timeout)
        except (TypeError, ValueError):
            self.timeout = 120.0
        if not (self.base_url and self.api_key and self.model):
            raise ImproperlyConfigured(
                "Translation API is not configured. Set TRANSLATION_API_BASE_URL, "
                "TRANSLATION_API_KEY and TRANSLATION_MODEL to any OpenAI-compatible "
                "endpoint (e.g. the z.ai general API: "
                "https://api.z.ai/api/paas/v4 with a GLM model)."
            )
        self._http = httpx.Client(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=self.timeout,
            transport=transport,
        )

    def close(self) -> None:
        self._http.close()

    def translate(
        self,
        texts: dict[str, str],
        source_lang: str,
        target_langs: t.Sequence[str],
        context: str = "",
    ) -> dict[str, dict[str, str]]:
        """Translate a batch of fields in one request.

        Args:
            texts: Mapping of field name to source text.
            source_lang: Language code of ``texts``.
            target_langs: Language codes to translate into.
            context: Short description of the object for proper-noun hints.

        Returns:
            Mapping ``{target_lang: {field: translated_text}}``. Missing
            languages/fields are absent from the result.
        """
        if not target_langs or not texts:
            return {}
        user_payload = {
            "source_lang": source_lang,
            "target_langs": list(target_langs),
            "context": context,
            "fields": texts,
        }
        content = self._complete(_SYSTEM_PROMPT, json.dumps(user_payload))
        return self._parse(content, target_langs, texts.keys())

    def _complete(self, system: str, user: str) -> str:
        payload = {
            "model": self.model,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        last_error: Exception | None = None
        for attempt in range(RETRIES):
            if attempt:
                time.sleep(RETRY_BACKOFF_SECONDS)
            try:
                response = self._http.post("chat/completions", json=payload)
                response.raise_for_status()
                data = response.json()
                return str(data["choices"][0]["message"]["content"])
            except httpx.HTTPStatusError as error:
                last_error = error
                retryable = error.response.status_code in RETRY_STATUS_CODES
                if not retryable:
                    raise TranslationError(
                        f"Translation API error (HTTP {error.response.status_code}): {error}"
                    ) from error
            except httpx.HTTPError as error:
                last_error = error  # transport errors: retry
            except (KeyError, IndexError, ValueError) as error:
                last_error = error  # malformed response: retry
        raise TranslationError(
            f"Translation API failed after {RETRIES} attempts: {last_error}"
        )

    @staticmethod
    def _parse(
        content: str,
        target_langs: t.Sequence[str],
        fields: t.Iterable[str],
    ) -> dict[str, dict[str, str]]:
        try:
            parsed = json.loads(TranslationClient._strip_fences(content))
        except ValueError as error:
            excerpt = content[:200].replace("\n", " ")
            raise TranslationError(
                f"Translation API returned invalid JSON: {excerpt!r}"
            ) from error
        result: dict[str, dict[str, str]] = {}
        if not isinstance(parsed, dict):
            raise TranslationError("Translation API JSON is not an object.")
        for lang in target_langs:
            translations = parsed.get(lang)
            if not isinstance(translations, dict):
                continue
            cleaned = {
                str(field): str(value)
                for field, value in translations.items()
                if field in fields and isinstance(value, str) and value
            }
            if cleaned:
                result[lang] = cleaned
        return result

    @staticmethod
    def _strip_fences(content: str) -> str:
        content = content.strip()
        if content.startswith("```"):
            first_newline = content.find("\n")
            if first_newline != -1:
                content = content[first_newline + 1 :]
            if content.rstrip().endswith("```"):
                content = content.rstrip()[:-3]
        return content.strip()

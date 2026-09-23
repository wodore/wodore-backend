"""Shared test doubles for the translations app."""

import typing as t


class FakeTranslationClient:
    """Deterministic stand-in for :class:`TranslationClient`.

    Echoes ``<source text>-<target lang>`` for every requested field unless
    ``result`` is given explicitly (``{lang: {field: text}}``).
    """

    def __init__(self, result: dict[str, dict[str, str]] | None = None) -> None:
        self.calls: list[dict[str, t.Any]] = []
        self.result = result

    def translate(
        self,
        texts: dict[str, str],
        source_lang: str,
        target_langs: t.Sequence[str],
        context: str = "",
    ) -> dict[str, dict[str, str]]:
        self.calls.append(
            {
                "texts": dict(texts),
                "source_lang": source_lang,
                "target_langs": list(target_langs),
                "context": context,
            }
        )
        if self.result is not None:
            return self.result
        return {
            lang: {field: f"{value}-{lang}" for field, value in texts.items()}
            for lang in target_langs
        }

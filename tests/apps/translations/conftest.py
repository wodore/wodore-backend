"""Shared test doubles for the translations app."""

import typing as t


class FakeTranslationClient:
    """Deterministic stand-in for :class:`TranslationClient`.

    Echoes ``<source text>-<target lang>`` for every requested field unless
    ``result`` is given explicitly (``{lang: {field: text}}``). When
    ``assess_source`` is requested, the result carries a ``source_quality``
    entry from ``quality``; ``assess()`` returns ``assess_result``.
    """

    def __init__(
        self,
        result: dict[str, dict[str, str]] | None = None,
        quality: dict[str, t.Any] | None = None,
        assess_result: dict[str, t.Any] | None = None,
    ) -> None:
        self.calls: list[dict[str, t.Any]] = []
        self.result = result
        self.quality = (
            quality
            if quality is not None
            else {"score": 7, "summary": "Solid hut description."}
        )
        self.assess_result = (
            assess_result
            if assess_result is not None
            else {"score": 7, "summary": "Solid hut description."}
        )

    def translate(
        self,
        texts: dict[str, str],
        source_lang: str,
        target_langs: t.Sequence[str],
        context: str = "",
        assess_source: bool = False,
    ) -> dict[str, t.Any]:
        self.calls.append(
            {
                "texts": dict(texts),
                "source_lang": source_lang,
                "target_langs": list(target_langs),
                "context": context,
                "assess_source": assess_source,
            }
        )
        if self.result is not None:
            out: dict[str, t.Any] = dict(self.result)
        else:
            out = {
                lang: {field: f"{value}-{lang}" for field, value in texts.items()}
                for lang in target_langs
            }
        if assess_source:
            out["source_quality"] = dict(self.quality)
        return out

    def assess(self, text: str, context: str = "") -> dict[str, t.Any]:
        self.calls.append({"assess": text, "context": context})
        return dict(self.assess_result)

"""Fill empty translated (modeltrans) fields of model instances via LLM."""

import inspect
import typing as t

from django.conf import settings

from server.apps.translations.llm import TranslationClient


class _Translator(t.Protocol):
    """Structural interface the service needs from a translation client."""

    def translate(
        self,
        texts: dict[str, str],
        source_lang: str,
        target_langs: t.Sequence[str],
        context: str = "",
    ) -> dict[str, dict[str, str]]: ...


TranslationResult = dict[str, t.Any]


def translated_field_names(obj: t.Any) -> tuple[str, ...]:
    """Names of the fields included in the model's ``i18n`` TranslationField."""
    i18n_field = obj._meta.get_field("i18n")
    return tuple(i18n_field.fields)


def localized_value(obj: t.Any, field: str, lang: str) -> str:
    """Raw value of a translated field in a language (``""`` if unset)."""
    if lang == settings.LANGUAGE_CODE:
        return getattr(obj, field) or ""
    return (obj.i18n or {}).get(f"{field}_{lang}") or ""


def _field_max_length(obj: t.Any, field: str) -> int | None:
    model_field = obj._meta.get_field(field)
    return getattr(model_field, "max_length", None)


def _supports_kwarg(obj: t.Any, kwarg: str) -> bool:
    signature = inspect.signature(type(obj).save)
    parameter = signature.parameters.get(kwarg)
    return parameter is not None and parameter.kind in (
        inspect.Parameter.KEYWORD_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        inspect.Parameter.VAR_KEYWORD,
    )


def _save_instance(obj: t.Any, update_fields: list[str]) -> None:
    kwargs: dict[str, t.Any] = {"update_fields": update_fields}
    if _supports_kwarg(obj, "track_modifications"):
        # GeoPlace: LLM translations must not mark records as manually
        # modified (which would protect them from source updates).
        kwargs["track_modifications"] = False
    obj.save(**kwargs)


def translate_instance(
    obj: t.Any,
    *,
    languages: t.Sequence[str] | None = None,
    fields: t.Sequence[str] | None = None,
    overwrite: bool = False,
    dry_run: bool = False,
    client: _Translator | None = None,
) -> TranslationResult:
    """Translate empty translated fields of one instance from its main language.

    Reads the source texts from ``obj.main_language`` (fallback: the default
    language) and fills only target-language fields that are empty — existing
    (e.g. human-made) translations are never touched unless ``overwrite`` is
    set. All fields of one instance are translated in a single API call.

    Args:
        obj: Model instance with an ``i18n`` TranslationField and a
            ``main_language`` field (currently Hut and GeoPlace).
        languages: Target language codes (default: all configured languages
            except the source language).
        fields: Translated field names to consider (default: all fields of
            the model's ``i18n`` TranslationField).
        overwrite: Also replace non-empty translations.
        dry_run: Report the planned translations without calling the API
            and without modifying the instance (no config needed).
        client: Prebuilt translation client (structural `translate()`
            interface, e.g. :class:`TranslationClient` or a test double;
            default: build one from settings when translations are actually
            needed; raises ``ImproperlyConfigured`` when unconfigured).

    Returns:
        Stats dict with ``source_lang``, ``translated`` (``{lang: [fields]}``),
        ``skipped_existing``, ``skipped_no_source``, ``too_long`` and ``saved``.
    """
    if client is None:
        client = None  # built lazily below, only when needed

    default_lang = settings.LANGUAGE_CODE
    source_lang = getattr(obj, "main_language", "") or default_lang
    all_fields = tuple(fields) if fields else translated_field_names(obj)
    targets = [
        lang for lang in (languages or settings.LANGUAGE_CODES) if lang != source_lang
    ]

    sources = {field: localized_value(obj, field, source_lang) for field in all_fields}
    skipped_no_source = [field for field, value in sources.items() if not value]

    missing = [
        (lang, field)
        for lang in targets
        for field in all_fields
        if (overwrite or not localized_value(obj, field, lang)) and sources[field]
    ]
    skipped_existing = [
        (lang, field)
        for lang in targets
        for field in all_fields
        if sources[field]
        and localized_value(obj, field, lang)
        and (lang, field) not in missing
    ]

    result: dict[str, dict[str, str]] = {}
    if missing and not dry_run:
        if client is None:
            client = TranslationClient()
        needed_langs = list(dict.fromkeys(lang for lang, _ in missing))
        needed_fields = list(dict.fromkeys(field for _, field in missing))
        result = client.translate(
            {field: sources[field] for field in needed_fields},
            source_lang,
            needed_langs,
            context=f"{obj.__class__.__name__} '{obj}'",
        )

    translated: dict[str, list[str]] = {}
    too_long: list[tuple[str, str, int]] = []
    update_fields = ["i18n"]
    for lang, field in missing:
        if dry_run:
            translated.setdefault(lang, []).append(field)
            continue
        value = (result.get(lang) or {}).get(field)
        if not value:
            continue
        max_length = _field_max_length(obj, field)
        if max_length is not None and len(value) > max_length:
            too_long.append((lang, field, len(value)))
            continue
        if not dry_run:
            # Descriptor routes this to the base column (default language)
            # or into the i18n JSONB.
            setattr(obj, f"{field}_{lang}", value)
            if lang == default_lang and field not in update_fields:
                update_fields.append(field)
        translated.setdefault(lang, []).append(field)

    if translated and not dry_run:
        _save_instance(obj, update_fields)

    return {
        "source_lang": source_lang,
        "translated": translated,
        "skipped_existing": skipped_existing,
        "skipped_no_source": skipped_no_source,
        "too_long": too_long,
        "saved": bool(translated) and not dry_run,
    }

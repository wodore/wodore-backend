"""Typed API schemas and helpers for the translations app."""

import typing as t

import pydantic
from pydantic import Field, create_model

from django.conf import settings

LANGUAGE_CODES = [lang[0] for lang in settings.LANGUAGES]


class LanguageQuery(pydantic.BaseModel):
    """Shared ``lang`` query parameter (former ninja ``LanguageParam``).

    Endpoints that take more query parameters subclass this and add
    their fields — one typed query model per endpoint.
    """

    model_config = pydantic.ConfigDict(extra="ignore")

    lang: str = Field(
        settings.DEFAULT_LANG,
        description=f"Select language code: {', '.join(LANGUAGE_CODES)}.",
        pattern=f"({'|'.join(LANGUAGE_CODES)})",
    )


lang_kwargs: t.Any = {
    lang[0]: (str | None, Field("", description=lang[1])) for lang in settings.LANGUAGES
}
TranslationSchema = create_model(
    "TranslationSchema", **lang_kwargs, __doc__="Translations"
)

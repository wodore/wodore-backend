import typing as t
from functools import wraps

from ninja import Query
from pydantic import Field, create_model

from django.conf import settings
from django.http import HttpRequest

LANGUAGE_CODES = [lang[0] for lang in settings.LANGUAGES]

LanguageParam = t.Annotated[
    str | None,
    Query(
        "de",
        description=f"Select language code: {', '.join(LANGUAGE_CODES)}.",  # or _empty_ for all.",
        # example=settings.LANGUAGE_CODE,
        pattern=f"({'|'.join(LANGUAGE_CODES)})",
    ),
]

lang_kwargs: t.Any = {lang[0]: (str | None, Field("", description=lang[1])) for lang in settings.LANGUAGES}
TranslationSchema = create_model("TranslationSchema", **lang_kwargs, __doc__="Translations")


def with_language_param(_param: str = "lang") -> t.Callable[[t.Callable[..., t.Any]], t.Callable[..., t.Any]]:
    """Returns object with the correct language, the paramter 'lang: LanguageParam' is still needed."""

    def decorator(func: t.Callable[..., t.Any]) -> t.Callable[..., t.Any]:
        @wraps(func)
        def wrapper(request: HttpRequest, *args: t.Any, **kwargs: t.Any) -> t.Any:
            assert _param in kwargs, f"Function paramter '{_param}: LanguageParam' is missing! "
            # lang = kwargs.get(_param)
            # with override(lang):
            return func(request, *args, **kwargs)

        return wrapper

    return decorator

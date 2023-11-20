from functools import wraps
from typing import Any, Callable
from django.http import HttpRequest
from django.utils.translation import get_language as django_get_language
from django.utils.translation import activate as django_activate
from django.utils.translation import deactivate as django_deactivate
from contextlib import ContextDecorator

# TODO activate django lang settings as well

_LANG = None


def activate(language):
    global _LANG
    _LANG = language
    return _LANG


def deactivate():
    global _LANG
    _LANG = None
    return _LANG


def get_language():
    global _LANG
    return _LANG


def with_language_param(_param: str = "lang") -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Returns object with the correct language, the paramter 'lang: LanguageParam' is still needed."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> Any:
            assert _param in kwargs, f"Function paramter '{_param}: LanguageParam' is missing! "
            lang = kwargs.get(_param)
            with override(lang):
                return func(request, *args, **kwargs)

        return wrapper

    return decorator


class override(ContextDecorator):
    def __init__(self, language=None, deactivate=False):
        if not language:
            self.language = None
        elif language.lower() in ["_", "default"]:
            self.language = django_get_normalised_language()
        else:
            self.language = language
        self.deactivate = deactivate

    def __enter__(self):
        # self.old_language = get_language()
        if self.language is not None:
            activate(self.language)
            django_activate(self.language)
        else:
            deactivate()
            django_deactivate()

    def __exit__(self, exc_type, exc_value, traceback):
        deactivate()
        django_deactivate()
        # if self.old_language is None:
        #    deactivate()
        # elif self.deactivate:
        #    deactivate()
        # else:
        #    activate(self.old_language)


def normalise_language_code(lang_code):
    """
    For consistency always operate on language codes
    that are lowercase and use dashes as separators for
    composed language codes.

    Example: 'en_GB' -> 'en-gb'
    """
    return lang_code.lower().replace("_", "-")


def get_normalised_language():
    lang = get_language()
    if lang:
        return normalise_language_code(lang)


def django_get_normalised_language():
    lang = django_get_language()
    if lang:
        return normalise_language_code(lang)

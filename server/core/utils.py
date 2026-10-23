import textwrap
from enum import Enum
from typing import Literal

import requests

from django.conf import settings
from django.core.cache import caches
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _


class UpdateCreateStatus(str, Enum):
    no_change = "no change"
    created = "created"
    updated = "updated"
    deleted = "deleted"
    exists = "exists"
    ignored = "ignored"


# Shared by the images and symbols media transformers (formerly two
# module-scoped hut-services ``@cached`` copies). 30 days: redirect targets
# (e.g. commons.wikimedia) are stable, and re-probing costs one HTTP HEAD
# inside the request path.
_REDIRECT_URL_TIMEOUT = 3600 * 24 * 30


def get_redirect_url(url: str) -> str:
    """Follow ``url``'s redirects and return the final URL, cached for 30 days.

    Stored in the ``persistent`` database cache (the repo's alias for
    long-term media data: shared across workers, survives restarts) under
    one ``media:redirect:`` namespace shared by all media transformers.
    Deliberately plain Django caching - generic media infrastructure must
    not couple to hut-services' cache (its keys embed the hut-services
    package version and its ``clear_cache()`` would evict these entries).
    A failing HEAD request is never cached: the exception propagates and
    the next call retries.
    """
    return caches["persistent"].get_or_set(
        f"media:redirect:{url}",
        lambda: (
            requests.head(
                url,
                allow_redirects=True,
                timeout=10,
                headers={"User-Agent": settings.BOT_AGENT},
            ).url
        ),
        timeout=_REDIRECT_URL_TIMEOUT,
    )


def text_shorten_html(
    text,
    width=100,
    textsize: Literal["xs", "sm", "base", "lg"] = "xs",
    klass="text-gray-500",
    on_word=True,
    placeholder="...",
    **kwargs,
):
    """Returns a shortened html text (uses textwrap.shortend)"""
    if on_word:
        text = textwrap.shorten(text, width=width, placeholder=placeholder, **kwargs)
    else:
        if len(text) > width - len(placeholder) - 1:
            text = f"{text[:width]}{placeholder}"
    return mark_safe(f'<span class="{klass} text-{textsize}">{text}<span/>')


def environment_callback(request):
    """
    Callback has to return a list of two values represeting text value and the color
    type of the label displayed in top right corner.

    Returns:
        - Production: ["Live", "warning"] or ["Live [debug]", "warning"] if DEBUG
        - Staging: ["Staging", "info"] or ["Staging [debug]", "info"] if DEBUG
        - Development: ["Dev", "info"] or ["Dev [debug]", "info"] if DEBUG
    """
    environment = getattr(settings, "ENVIRONMENT", None)

    # Determine environment label and color
    if environment == "production":
        label = _("Live")
        color = "warning"
    elif environment == "staging":
        label = _("Staging")
        color = "info"
    else:
        # Default to development
        label = _("Dev")
        color = "info"

    # Append [debug] if DEBUG is enabled
    if settings.DEBUG:
        label = f"{label} [debug]"

    return [mark_safe(str(label)), color]

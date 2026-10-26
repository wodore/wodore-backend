import secrets
import string
import textwrap
from collections.abc import Collection
from enum import Enum
from typing import Any, Literal

import requests
from slugify import slugify as pyslugify

from django.conf import settings
from django.core.cache import caches
from django.http import HttpRequest
from django.utils.safestring import SafeString, mark_safe
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
    return caches["persistent"].get_or_set(  # type: ignore  # cached getattr loses type
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
    text: str,
    width: int = 100,
    textsize: Literal["xs", "sm", "base", "lg"] = "xs",
    klass: str = "text-gray-500",
    on_word: bool = True,
    placeholder: str = "...",
    **kwargs: Any,
) -> SafeString:
    """Returns a shortened html text (uses textwrap.shortend)"""
    if on_word:
        text = textwrap.shorten(text, width=width, placeholder=placeholder, **kwargs)
    else:
        if len(text) > width - len(placeholder) - 1:
            text = f"{text[:width]}{placeholder}"
    return mark_safe(f'<span class="{klass} text-{textsize}">{text}<span/>')


# Short-slug minting (extracted from GeoPlace.generate_unique_slug,
# OpenSpec change ``party-slug-minting``): shared by geoplaces and
# parties. Pure function - deterministic base, random suffix, no DB.

#: Target length of the readable base part (leaves room for a
#: 5-char random suffix under the default ``max_length`` of 15).
_SLUG_BASE_TARGET = 9


def mint_short_slug(
    name: str,
    *,
    fallback: str = "place",
    ignore_words: Collection[str] = (),
    max_length: int = 15,
) -> str:
    """Mint a short readable public slug ``{base}-{suffix}`` (no DB check).

    The base is derived deterministically from ``name`` (slugified,
    ``ignore_words`` filtered, up to 3 words of >= 3 chars distributed
    over a ~9-char target); empty or fully filtered names fall back to
    ``fallback``. The suffix is drawn from ``[a-z0-9]`` with a
    cryptographic random source, sized 5-8 chars from the space
    ``max_length`` leaves; the result is clamped to ``max_length``.

    Uniqueness is probabilistic (36^5 ~= 60M minimum suffix space) -
    creation sites that need certainty retry on ``IntegrityError``.

    Examples (geoplace configuration)::

        "Liechtensteinisches Landesspital" -> "liechtenst-dne4"
        "Gemeindepolizei Schellenberg" -> "gemeindepo-wz9j"
        "Lio" -> "lio-3k8m9x4"
        "" (fallback "place") -> "place-vn191wad"
    """
    # 1. Fallback for empty names
    if not name or len(name.strip()) < 2:
        base_slug = fallback
    else:
        # 2. Create base slug
        slug = pyslugify(name, word_boundary=True)
        slug = slug.strip("-")

        # 3. Filter ignorable words (call-site vocabulary)
        words = [w for w in slug.split("-") if w not in ignore_words and len(w) >= 3]

        if not words:
            base_slug = fallback
        else:
            # 4. Smart word splitting: take up to 3 words, distribute
            # space equally over the base target length
            selected_words = words[:3]
            num_words = len(selected_words)
            chars_per_word = max(3, _SLUG_BASE_TARGET // num_words)

            word_parts = [word[:chars_per_word] for word in selected_words]
            base_slug = "".join(word_parts)

            # If we have space left, extend the first word
            remaining = _SLUG_BASE_TARGET - len(base_slug)
            if remaining > 0 and len(selected_words[0]) > chars_per_word:
                extended_first = selected_words[0][: chars_per_word + remaining]
                base_slug = extended_first + "".join(word_parts[1:])

            base_slug = base_slug[:_SLUG_BASE_TARGET]

    # 5. Smart suffix sizing (min 5, max 8)
    available_space = max_length - len(base_slug) - 1
    suffix_len = max(5, min(8, available_space))

    # 6. Random suffix
    charset = string.ascii_lowercase + string.digits
    suffix = "".join(secrets.choice(charset) for _ in range(suffix_len))

    # 7. Combine and enforce max length
    slug = f"{base_slug}-{suffix}"
    return slug[:max_length]


def environment_callback(request: HttpRequest) -> list[str]:
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

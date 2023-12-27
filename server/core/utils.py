import textwrap
from enum import Enum
from typing import Literal

from django.conf import settings
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _


class UpdateCreateStatus(str, Enum):
    no_change = "no change"
    created = "created"
    updated = "updated"
    deleted = "deleted"
    exists = "exists"
    ignored = "ignored"


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
    """
    if settings.DEBUG:
        return ["Dev", "info"]  # info, danger, warning, success
    # icon = '<span class="material-symbols-outlined"> cell_tower </span>'
    return [mark_safe(f"{_('Live')}"), "warning"]  # info, danger, warning, success

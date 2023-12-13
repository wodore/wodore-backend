import textwrap
from typing import Literal

from django.utils.safestring import mark_safe


def text_shorten_html(
    text,
    width=100,
    textsize: Literal["xs", "sm", "base", "lg"] = "xs",
    klass="text-gray-500",
    placeholder="...",
    **kwargs,
):
    """Returns a shortened html text (uses textwrap.shortend)"""
    note = textwrap.shorten(text, width=width, placeholder=placeholder, **kwargs)
    return mark_safe(f'<span class="{klass} text-{textsize}">{note}<span/>')

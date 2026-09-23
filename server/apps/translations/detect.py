"""Language detection for translated content."""

import typing as t
from collections.abc import Mapping

from django.conf import settings


def detect_main_language(
    values: Mapping[str, str | None],
    priority: t.Sequence[str] | None = None,
) -> str | None:
    """Return the language code of the main language for a set of translations.

    Picks the first non-empty value in ``priority`` order (default: the
    configured ``LANGUAGE_CODES`` order, i.e. German first). This mirrors the
    historic ``primary_name()`` behaviour in the hut model.

    Args:
        values: Mapping of language code to text (``None``/empty are ignored).
        priority: Language codes in preference order.

    Returns:
        The detected language code, or ``None`` if no value is set.
    """
    order = priority if priority is not None else settings.LANGUAGE_CODES
    for code in order:
        if values.get(code):
            return code
    return None

"""Phone normalization for typed URI links (openspec: external-link-uris).

Every phone number normalizes to international E.164 (``+<countrycode>
<number>``) via the ``phonenumbers`` library (Google libphonenumber
port) before it becomes a ``tel:`` ``uri.phone`` ExternalLink. The
region for national numbers chains from the place's ``country_code``,
falling back to ``CH``; numbers that cannot be parsed are flagged for
review, never silently dropped.
"""

from __future__ import annotations

import phonenumbers

#: Region used when neither the number nor the place says otherwise —
#: the wodore dataset is alps-centric.
DEFAULT_REGION = "CH"


def normalize_phone_e164(number: str, region: str | None = None) -> str | None:
    """Normalize one phone number to E.164 (``None`` when unparseable).

    Args:
        number: the raw number (OSM ``phone`` / ``contact:phone`` or
            the JSON block's ``number``).
        region: ISO country code hint for national numbers — the
            place's ``country_code``; falls back to ``DEFAULT_REGION``.
    """
    cleaned = (number or "").strip()
    if not cleaned:
        return None
    # Multiple numbers in one tag (OSM allows ';'-separated) — the
    # caller handles splitting; a lone value with separators is not a
    # single number.
    if ";" in cleaned:
        return None
    try:
        parsed = phonenumbers.parse(cleaned, region or DEFAULT_REGION)
    except phonenumbers.NumberParseException:
        # A bare + number with a broken structure still fails here;
        # callers flag it for review.
        return None
    if not phonenumbers.is_valid_number(parsed):
        return None
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def tel_url(e164: str) -> str:
    """The ``tel:`` URL for an E.164 number (RFC 3966 global number)."""
    return f"tel:{e164}"

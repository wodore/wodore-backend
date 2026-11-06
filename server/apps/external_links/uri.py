"""Typed-URI helpers for external links (openspec: external-link-uris).

``ExternalLink.url`` accepts any scheme its URI kind allows — the
http(s)-only ``URLField`` became a scheme-aware character field whose
validator dispatches per scheme: http(s) → Django's ``URLValidator``,
``tel:`` → RFC 3966 phone URI, ``mailto:`` → address check. Anything
else is rejected (a vocabulary kind must accept it — kinds are the
extensible dimension, schemes per kind live in the category's
``extra["schemes"]``).
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator, validate_email

#: Schemes the web machinery (source detection, title extraction,
#: health checks) is defined over. Everything else is transport-only.
WEB_SCHEMES: tuple[str, ...] = ("http", "https")

#: RFC 3966 phone URI (global numbers start with ``+``; visual
#: separators per the RFC are ``-``/``.``/``(``)``/space; local numbers
#: without a region are allowed through storage — normalization to
#: E.164 happens at write time via ``phonenumbers``).
_TEL_RE = re.compile(r"^tel:[0-9\-\.\(\)\s]*\+?[0-9][0-9\-\.\(\)\s]*$", re.IGNORECASE)

_web_validator = URLValidator(schemes=list(WEB_SCHEMES))


def scheme_of(url: str | None) -> str | None:
    """Lower-cased scheme of ``url`` (``None`` when unparseable/absent)."""
    if not url:
        return None
    scheme = urlparse(url).scheme
    return scheme.lower() or None


def is_web_url(url: str | None) -> bool:
    """Whether the web-only auto-behaviours apply to this URL."""
    return scheme_of(url) in WEB_SCHEMES


def validate_url_for_scheme(url: str) -> None:
    """Scheme-aware well-formedness check (dispatch per scheme).

    Raises ``ValidationError`` for unknown schemes or malformed URIs —
    the storage-layer counterpart of the scheme↔kind consistency
    enforced in ``ExternalLink.clean()``.
    """
    scheme = scheme_of(url)
    if scheme in WEB_SCHEMES:
        _web_validator(url)
        return
    if scheme == "tel":
        if not _TEL_RE.match(url.strip()):
            msg = f"'{url}' is not a valid tel: URI (RFC 3966, e.g. tel:+41441234567)."
            raise ValidationError(msg)
        return
    if scheme == "mailto":
        address = url.split(":", 1)[1].split("?", 1)[0].strip()
        try:
            validate_email(address)
        except ValidationError as exc:
            msg = f"'{url}' is not a valid mailto: URI ({exc})."
            raise ValidationError(msg) from exc
        return
    msg = (
        f"URL scheme '{scheme or '<none>'}:' is not supported — no URI kind "
        f"accepts it (http/https, tel, mailto)."
    )
    raise ValidationError(msg)

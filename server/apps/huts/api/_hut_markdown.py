"""Markdown rendering of a single hut for LLM agents (and humans).

``/v1/huts/{slug}.md`` returns the same public data as the JSON detail
endpoint, but as a small, self-contained Markdown document that LLMs can
ingest and cite directly (linked from ``/llms.txt``). Localized via the
same ``lang`` parameter as the JSON API, with the same fallback behavior
(modeltrans resolves the active language and falls back to the hut's
main language).

Plain Django view (non-JSON), wired via ``external_path`` with
``openapi=None`` — hidden from the schema like before.
"""

from __future__ import annotations

import re
from html import unescape
from urllib.parse import quote

from django.conf import settings
from django.http import Http404, HttpRequest, HttpResponse
from django.utils.html import strip_tags

from server.apps.translations import activate

from ..models import Hut

# Endonym labels for the language variant links in the Markdown footer.
_LANGUAGE_LABELS = {
    "de": "Deutsch",
    "en": "English",
    "fr": "Français",
    "it": "Italiano",
}


def _languages_line(slug: str) -> str:
    """Footer links to this document in every supported language."""
    base = f"{settings.FRONTEND_DOMAIN.rstrip('/')}/hut/{quote(slug)}.md"
    links = [
        f"[{label}]({base}?lang={code})" for code, label in _LANGUAGE_LABELS.items()
    ]
    return " · ".join(links)


_ANCHOR_RE = re.compile(
    r'<a\s[^>]*href=["\']([^"\']*)["\'][^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL
)

# Cacheable like the JSON surface: hut data changes, but slowly.
CACHE_TTL = 60 * 60


def _attribution_as_markdown(value: str) -> str:
    """Convert the stored HTML attribution to a Markdown string.

    ``&copy; <a href="...">SAC-CAS</a>`` becomes ``© [SAC-CAS](...)`` —
    the legal attribution (link + name) is preserved verbatim in meaning.
    """

    def to_link(match: re.Match[str]) -> str:
        href = match.group(1).strip()
        label = strip_tags(match.group(2)).strip() or href
        return f"[{label}]({href})"

    text = strip_tags(_ANCHOR_RE.sub(to_link, value))
    return unescape(text).strip()


def _fmt_elevation(elevation) -> str | None:
    if elevation is None:
        return None
    return f"{int(elevation)} m"


def _fmt_coordinates(point) -> str | None:
    if point is None:
        return None
    return f"{point.y:.6f}, {point.x:.6f}"


def _months_row(open_monthly: dict | None) -> str:
    values = []
    for month in range(1, 13):
        value = (open_monthly or {}).get(f"month_{month:02d}", "unknown")
        values.append(str(value))
    return "| " + " | ".join(values) + " |"


def _hut_markdown(request: HttpRequest, hut: Hut) -> str:
    app_url = f"{settings.FRONTEND_DOMAIN.rstrip('/')}/hut/{hut.slug}"
    json_url = request.build_absolute_uri(f"/v1/huts/{quote(hut.slug)}")

    subtitle = " · ".join(
        part
        for part in (
            hut.hut_type_open.name if hut.hut_type_open else None,
            _fmt_elevation(hut.elevation),
            hut.hut_owner.name if hut.hut_owner else None,
            hut.country_field.name if hut.country_field else None,
        )
        if part
    )

    overview: list[tuple[str, str]] = [
        (
            "Type (standard operation)",
            hut.hut_type_open.name if hut.hut_type_open else None,
        ),
        (
            "Type (reduced operation)",
            hut.hut_type_closed.name if hut.hut_type_closed else None,
        ),
        ("Elevation", _fmt_elevation(hut.elevation)),
        ("Coordinates", _fmt_coordinates(hut.location)),
        (
            "Capacity (standard operation)",
            f"{hut.capacity_open}" if hut.capacity_open else None,
        ),
        (
            "Capacity (reduced operation)",
            f"{hut.capacity_closed}" if hut.capacity_closed else None,
        ),
        ("Owner", hut.hut_owner.name if hut.hut_owner else None),
        ("Website", hut.url or None),
    ]
    overview_rows = "\n".join(
        f"| {label} | {value} |" for label, value in overview if value
    )

    open_info_url = (hut.open_monthly or {}).get("url")
    attribution = _attribution_as_markdown(hut.description_attribution)
    attribution_line = f"\n*Description: {attribution}*\n" if attribution else ""

    sources = []
    for association in hut.orgs_source.select_related("organization").order_by(
        "organization__order", "organization__slug"
    ):
        organization = association.organization
        label = organization.name or organization.fullname or organization.slug
        link = association.link
        sources.append(f"- [{label}]({link})" if link else f"- {label}")
    sources_block = "\n".join(sources)

    return f"""# {hut.name}

> {subtitle}

Interactive map: {app_url}

## Overview

| | |
| --- | --- |
{overview_rows}

## Open months

| Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
{_months_row(hut.open_monthly)}

{f"Opening information: {open_info_url}" if open_info_url else ""}

## Description

{hut.description}
{attribution_line}
Languages: {_languages_line(hut.slug)}

## Sources

{sources_block}

---

Data: [Wodore]({settings.FRONTEND_DOMAIN.rstrip("/")}) · JSON: {json_url} · Last updated: {hut.modified:%Y-%m-%d}
"""


def get_hut_markdown(request: HttpRequest, slug: str, lang: str = "de") -> HttpResponse:
    """Get a hut by its slug, rendered as Markdown for LLM agents."""
    activate(lang)
    hut = (
        Hut.objects.select_related("hut_owner", "hut_type_open", "hut_type_closed")
        .filter(is_active=True, is_public=True, slug=slug)
        .first()
    )
    if hut is None:
        msg = f"Could not find '{slug}'."
        raise Http404(msg)

    response = HttpResponse(
        _hut_markdown(request, hut), content_type="text/markdown; charset=utf-8"
    )
    response["Cache-Control"] = f"public, max-age={CACHE_TTL}"
    return response

"""Icon search endpoint (/v1/icons) — openspec: icon-library.

Public, read-only, ETag-cached ranked search over the icon registry:

- ``search`` matches localized keywords (``IconKeyword``, folded) and
  slugs with prefix ranked above substring; typo tolerance (Levenshtein
  ≤ 2) kicks in for terms ≥ 4 characters only when no exact match
  exists (design D6). Multiple terms AND-combine.
- ``pack`` / ``category`` (CLDR subgroup) / ``list`` (curated
  shortlist, e.g. ``activities``) are facets;
  ``limit``/``offset`` paginate. Without ``search`` results follow the
  stable ``(order, pack, slug)`` sort — ``list=<slug>`` then yields
  that curated shortlist.
- Keyword matching unions the requested locale with English so sparse
  locale data degrades gracefully.
"""

import hashlib
import json
from datetime import datetime
from http import HTTPStatus
from typing import NamedTuple

import pydantic
from dmr import Query, ResponseSpec, validate
from dmr.headers import HeaderSpec
from dmr.routing import path
from pydantic import Field

from django.conf import settings
from django.db import connection
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.utils.http import http_date

from server.apps.api.controller import ApiController
from server.apps.apiversions.transforms import version_cache_key
from server.apps.categories.models import Category
from server.apps.symbols.icon_data import fold_keyword
from server.apps.symbols.models import (
    Icon,
    IconKeyword,
    SymbolCollection,
)
from server.apps.symbols.utils import resolve_symbol_urls

CACHE_MAX_AGE = 60 * 60  # 1 hour — curated-list changes propagate fast;
# the ETag keeps revalidation correct, hard refresh is immediate
DEFAULT_LIMIT = 50
MAX_LIMIT = 200
FUZZY_MIN_TERM_LEN = 4
FUZZY_MAX_EDIT_DISTANCE = 2
FUZZY_CANDIDATE_CAP = 5000
_FACET_LIMIT = 5000  # bounded scan set for ranked search (design risks)

# Rank tiers: lower sorts first (design D6: prefix > substring > fuzzy).
RANK_EXACT = 0
RANK_PREFIX = 1
RANK_SUBSTRING = 2
RANK_FUZZY = 3

_CACHE_HEADER_SPECS = {
    "ETag": HeaderSpec(description="Content hash (API-version keyed)"),
    "Last-Modified": HeaderSpec(description="Last modification date"),
    "Cache-Control": HeaderSpec(description="Caching policy"),
}


class _IconMeta(NamedTuple):
    """Ranking-relevant fields of one icon (the cheap scan set)."""

    pk: int
    order: int
    pack: str
    slug: str


class IconsQuery(
    LanguageQuery := __import__(
        "server.apps.translations.schema", fromlist=["LanguageQuery"]
    ).LanguageQuery
):
    """Query parameters of the icons endpoint."""

    search: str = Field(
        "",
        description=(
            "Search term(s); matches localized keywords and slugs with "
            "typo tolerance. Empty returns browsable (faceted) results."
        ),
    )
    pack: str | None = Field(None, description="Filter by pack slug")
    slug: str | None = Field(
        None,
        description=(
            "Exact icon slug lookup (combine with pack to resolve one stored icon)"
        ),
    )
    category: str | None = Field(
        None,
        description=(
            "Filter by CLDR subgroup slug (a group slug matches all its subgroups)"
        ),
    )
    list: str | None = Field(
        None,
        description="Only icons of this curated list (slug, e.g. 'activities')",
    )
    limit: int = Field(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT, description="Page size")
    offset: int = Field(0, ge=0, description="Pagination offset")


class IconUrls(pydantic.BaseModel):
    """Per-style asset URLs of an icon."""

    detailed: str | None = Field(None, description="Detailed style SVG URL")
    simple: str | None = Field(None, description="Simple style SVG URL")
    mono: str | None = Field(None, description="Mono style SVG URL")


class IconDto(pydantic.BaseModel):
    """One icon of the registry."""

    slug: str = Field(description="Icon slug, unique within its pack")
    pack: str = Field(description="Pack slug")
    unicode: str | None = Field(
        None, description="Unicode hexcode(s), variation selectors stripped"
    )
    category: str | None = Field(None, description="CLDR group slug")
    subcategory: str | None = Field(None, description="CLDR subgroup slug")
    lists: list[str] = Field(description="Slugs of curated lists containing this icon")
    urls: IconUrls | None = Field(description="Per-style asset URLs")


def _levenshtein_within(left: str, right: str, limit: int) -> bool:
    """Bounded Levenshtein: True when ``edit_distance <= limit``."""
    if abs(len(left) - len(right)) > limit:
        return False
    previous = list(range(len(right) + 1))
    for i, left_char in enumerate(left, start=1):
        current = [i]
        row_min = i
        for j, right_char in enumerate(right, start=1):
            cost = 0 if left_char == right_char else 1
            value = min(
                previous[j] + cost if cost else previous[j],
                current[j - 1] + 1,
                previous[j - 1] + cost,
            )
            current.append(value)
            row_min = min(row_min, value)
        if row_min > limit:
            return False
        previous = current
    return previous[-1] <= limit


def _match_locales(lang: str) -> list[str]:
    """Requested locale plus English fallback (sparse locale data)."""
    return [lang] if lang == "en" else [lang, "en"]


def _keyword_matches(term: str, langs: list[str]) -> dict[int, int]:
    """Exact/prefix/substring keyword matches: ``icon_id -> best rank``."""
    rows = IconKeyword.objects.filter(
        locale__in=langs, keyword_folded__contains=term
    ).values_list("icon_id", "keyword_folded")
    matches: dict[int, int] = {}
    for icon_id, folded in rows:
        if folded == term:
            rank = RANK_EXACT
        elif folded.startswith(term):
            rank = RANK_PREFIX
        else:
            rank = RANK_SUBSTRING
        if icon_id not in matches or rank < matches[icon_id]:
            matches[icon_id] = rank
    return matches


def _slug_matches(term: str, metas: list[_IconMeta]) -> dict[int, int]:
    """Exact/prefix/substring slug matches within the facet result set."""
    matches: dict[int, int] = {}
    for meta in metas:
        folded = fold_keyword(meta.slug)
        if folded == term:
            rank = RANK_EXACT
        elif folded.startswith(term):
            rank = RANK_PREFIX
        elif term in folded:
            rank = RANK_SUBSTRING
        else:
            continue
        matches[meta.pk] = rank
    return matches


def _fuzzy_matches(term: str, langs: list[str]) -> dict[int, int]:
    """Typo tolerance: Levenshtein ≤ 2 keyword matches (rank RANK_FUZZY).

    Candidates are bounded to keywords sharing the first character —
    capped scan keeps the CPU bounded (design risks).
    """
    if len(term) < FUZZY_MIN_TERM_LEN:
        return {}
    candidate_rows = (
        IconKeyword.objects.filter(
            locale__in=langs, keyword_folded__istartswith=term[0]
        )
        .order_by("pk")
        .values_list("icon_id", "keyword_folded")[:FUZZY_CANDIDATE_CAP]
    )
    matches: dict[int, int] = {}
    for icon_id, folded in candidate_rows:
        if _levenshtein_within(term, folded, FUZZY_MAX_EDIT_DISTANCE):
            matches[icon_id] = RANK_FUZZY
    return matches


def _ranked_ids(
    metas: list[_IconMeta], terms: list[str], langs: list[str]
) -> list[int]:
    """Icon ids matching ALL terms, ordered best-first.

    ``metas`` is the facet-filtered base set (capped); keyword matches
    outside it are discarded. Per term the best match rank of an icon
    counts; the icon's total rank is the worst (max) across terms. Ties
    break by ``(order, pack, slug)`` — deterministic across pages
    (same-slug icons in both packs would otherwise order by row return
    order; the primary pack wins).
    """
    metas_by_id = {meta.pk: meta for meta in metas}
    per_term: list[dict[int, int]] = []
    for term in terms:
        matches = _keyword_matches(term, langs)
        for icon_id, rank in _slug_matches(term, metas).items():
            if icon_id not in matches or rank < matches[icon_id]:
                matches[icon_id] = rank
        if not matches:
            # Typo tolerance only when the term matches nothing exactly.
            matches = _fuzzy_matches(term, langs)
        matches = {
            icon_id: rank for icon_id, rank in matches.items() if icon_id in metas_by_id
        }
        if not matches:
            return []
        per_term.append(matches)
    common = set.intersection(*(set(m) for m in per_term))
    return sorted(
        common,
        key=lambda icon_id: (
            max(m[icon_id] for m in per_term),
            metas_by_id[icon_id].order,
            metas_by_id[icon_id].pack,
            metas_by_id[icon_id].slug,
        ),
    )


def _facet_base(query: IconsQuery):
    """Active icons under the facet filters, stable ``(order, pack, slug)``."""
    base = Icon.objects.filter(is_active=True).order_by("order", "pack__slug", "slug")
    if query.pack:
        base = base.filter(pack__slug=query.pack)
    if query.slug:
        base = base.filter(slug=query.slug)
    if query.list:
        base = base.filter(curated_lists__slug=query.list)
    if query.category:
        base = base.filter(
            Q(category__slug=query.category)
            | Q(category__identifier=query.category)
            | Q(category__parent__slug=query.category)
        )
    return base


def _facet_metas(query: IconsQuery) -> list[_IconMeta]:
    """Ranking scan set: ``(pk, order, pack, slug)`` tuples, no heavy joins.

    Bounded like the previous full-row scan (design risks); keyword
    matching and slug folding need exactly these fields.
    """
    return [
        _IconMeta(pk, order, pack, slug)
        for pk, order, pack, slug in _facet_base(query).values_list(
            "pk", "order", "pack__slug", "slug"
        )[:_FACET_LIMIT]
    ]


def _hydrate(icon_ids: list[int]) -> list[Icon]:
    """Load full icons for one page, preserving the given order."""
    icons = (
        Icon.objects.filter(pk__in=icon_ids)
        .select_related(
            "pack",
            "category__parent",
            "symbol_detailed",
            "symbol_simple",
            "symbol_mono",
        )
        .prefetch_related("curated_lists")
    )
    by_id = {icon.pk: icon for icon in icons}
    return [
        icon
        for icon_id in icon_ids
        # Graceful skip: an icon deactivated/deleted between the scan
        # and hydration queries must not crash the request.
        if (icon := by_id.get(icon_id)) is not None
    ]


def _search(query: IconsQuery) -> list[Icon]:
    """Resolve one icons request to a page of icons.

    Ranking runs on the cheap meta scan set; only the result page is
    hydrated with joins/prefetches (≤ ``limit`` rows, not the whole
    facet set).
    """
    metas = _facet_metas(query)
    terms = [
        folded for folded in (fold_keyword(t) for t in query.search.split()) if folded
    ]
    if not terms:
        page = [meta.pk for meta in metas][query.offset : query.offset + query.limit]
        return _hydrate(page)
    langs = _match_locales(query.lang)
    ids = _ranked_ids(metas, terms, langs)
    return _hydrate(ids[query.offset : query.offset + query.limit])


def _to_dto(icon: Icon, request: HttpRequest) -> IconDto:
    """Serialize one icon to the wire schema (task 2.2)."""
    category = icon.category
    urls = resolve_symbol_urls(icon, {"request": request})
    return IconDto(
        slug=icon.slug,
        pack=icon.pack.slug,
        unicode=icon.unicode or None,
        category=category.parent.slug if category else None,
        subcategory=category.slug if category else None,
        lists=sorted(
            cl.slug  # pyright: ignore[reportAttributeAccessIssue]  # reverse M2M: django-stubs gap
            for cl in icon.curated_lists.all()  # pyright: ignore[reportAttributeAccessIssue]  # reverse M2M: django-stubs gap
        ),
        urls=IconUrls.model_validate(urls) if urls else None,
    )


def _registry_maxima() -> dict[str, datetime | None]:
    """Modified maxima of every ETag-relevant table in ONE roundtrip.

    Per-table maxima (NOT a global max): a change in any single table
    must invalidate, even when another table is newer. Both the ETag
    and Last-Modified derive from this single read. Fully literal SQL
    (no parameters, no interpolation): the table names are stable
    schema facts, and a compound SELECT cannot reference the ORM
    Meta.ordering anyway.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT "
            "(SELECT MAX(modified) FROM symbols_icon), "
            "(SELECT MAX(modified) FROM symbols_iconkeyword), "
            "(SELECT MAX(modified) FROM symbols_symbol), "
            "(SELECT MAX(modified) FROM symbols_iconcuratedlist), "
            "(SELECT MAX(modified) FROM symbols_iconcuratedlistentry)"
        )
        icon, keyword, symbol, list_, entry = cursor.fetchone()
    return {
        "icon": icon,
        "keyword": keyword,
        "symbol": symbol,
        "list": list_,
        "entry": entry,
    }


def _last_modified_from(maxima: dict[str, datetime | None]) -> str:
    """http-date of the latest registry modification.

    Covers every registry table, not only the asset slots: curated-list
    edits change response bytes and must refresh Last-Modified too.
    """
    latest = max(
        (value for value in maxima.values() if value is not None),
        default=None,
    )
    return http_date(latest.timestamp()) if latest else http_date(0)


def _etag(
    request: HttpRequest, query: IconsQuery, maxima: dict[str, datetime | None]
) -> str:
    """Content ETag over the registry state + request keys.

    Keyed on the per-table modification maxima (re-imports and asset
    replacements invalidate), a content hash of the emoji taxonomy
    slugs (the response only ever carries slugs — localized category
    names do not surface, so renames alone need not invalidate), and
    the query parameters + API version (versioned 304 safety).
    """
    parts = [
        str(maxima["icon"]),
        str(maxima["keyword"]),
        str(maxima["symbol"]),
        # Curated-list membership is timestamped via the explicit through
        # model, so admin curation invalidates immediately.
        str(maxima["list"]),
        str(maxima["entry"]),
        repr(
            list(SymbolCollection.objects.order_by("pk").values_list("slug", "extra"))
        ),
        json.dumps(
            list(
                Category.objects.filter(
                    Q(parent__slug="emoji") | Q(parent__parent__slug="emoji")
                )
                # Stable row order: sort_keys does not sort list rows,
                # and physical order would jitter the hash.
                .order_by("id")
                .values_list("id", "slug")
            ),
            sort_keys=True,
            default=str,
        ),
        settings.MEDIA_URL,
        query.search,
        query.lang,
        query.pack or "",
        query.category or "",
        query.list or "",
        str(query.limit),
        str(query.offset),
        version_cache_key(request),
    ]
    digest = hashlib.sha256("-".join(parts).encode()).hexdigest()
    return f'"{digest}"'


def _etag_matches(request: HttpRequest, etag: str) -> bool:
    """If-None-Match check (huts etag_utils convention)."""
    if_none_match = request.headers.get("If-None-Match")
    if not if_none_match:
        return False
    request_etags = [tag.strip() for tag in if_none_match.split(",")]
    return etag in request_etags or "*" in request_etags


class IconsController(ApiController):
    """Searchable icon registry (emoji packs, openspec: icon-library)."""

    @validate(
        ResponseSpec(
            list[IconDto],
            status_code=HTTPStatus.OK,
            headers=_CACHE_HEADER_SPECS,
        ),
        ResponseSpec(
            None,
            status_code=HTTPStatus.NOT_MODIFIED,
            headers=_CACHE_HEADER_SPECS,
        ),
        description="Ranked icon search (ETag-cached).",
        operation_id="get_icons",
        exclude_validate_responses={HTTPStatus.NOT_MODIFIED},
    )
    def get(self, parsed_query: Query[IconsQuery]) -> HttpResponse:
        """Search icons.

        Ranked localized keyword search with typo tolerance; without a
        search term, browsable results (curated shortlist, pack or
        category facets) paginated by limit/offset.
        """
        request: HttpRequest = self.request
        query = parsed_query
        maxima = _registry_maxima()
        etag = _etag(request, query, maxima)
        last_modified = _last_modified_from(maxima)
        if _etag_matches(request, etag):
            return self.to_response(
                None,
                status_code=HTTPStatus.NOT_MODIFIED,
                headers={
                    "ETag": etag,
                    "Last-Modified": last_modified,
                    "Cache-Control": f"public, max-age={CACHE_MAX_AGE}",
                },
            )
        icons = _search(query)
        data = [_to_dto(icon, request) for icon in icons]
        return self.to_response(
            data,
            headers={
                "ETag": etag,
                "Last-Modified": last_modified,
                "Cache-Control": f"public, max-age={CACHE_MAX_AGE}",
            },
        )


paths = [
    path("", IconsController.as_view(), name="get_icons"),
]

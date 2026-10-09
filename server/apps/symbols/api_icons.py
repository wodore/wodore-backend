"""Icon search endpoint (/v1/icons) — openspec: icon-library.

Public, read-only, ETag-cached ranked search over the icon registry:

- ``search`` matches localized keywords (``IconKeyword``, folded) and
  slugs with prefix ranked above substring; typo tolerance (Levenshtein
  ≤ 2) kicks in for terms ≥ 4 characters only when no exact match
  exists (design D6). Multiple terms AND-combine.
- ``pack`` / ``category`` (CLDR subgroup) / ``list`` (curated
  shortlist, e.g. ``activities``) are facets;
  ``limit``/``offset`` paginate. Without ``search`` results follow the
  stable ``(order, slug)`` sort — ``list=<slug>`` then yields that
  curated shortlist.
- Keyword matching unions the requested locale with English so sparse
  locale data degrades gracefully.
"""

import hashlib
import json
from http import HTTPStatus

import pydantic
from dmr import Query, ResponseSpec, validate
from dmr.headers import HeaderSpec
from dmr.routing import path
from pydantic import Field

from django.conf import settings
from django.db.models import Max, Q
from django.http import HttpRequest, HttpResponse
from django.utils.http import http_date

from server.apps.api.controller import ApiController
from server.apps.apiversions.transforms import version_cache_key
from server.apps.categories.models import Category
from server.apps.symbols.icon_data import fold_keyword
from server.apps.symbols.models import (
    Icon,
    IconCuratedList,
    IconCuratedListEntry,
    IconKeyword,
    Symbol,
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


def _slug_matches(term: str, icons: list[Icon]) -> dict[int, int]:
    """Exact/prefix/substring slug matches within the facet result set."""
    matches: dict[int, int] = {}
    for icon in icons:
        folded = fold_keyword(icon.slug)
        if folded == term:
            rank = RANK_EXACT
        elif folded.startswith(term):
            rank = RANK_PREFIX
        elif term in folded:
            rank = RANK_SUBSTRING
        else:
            continue
        matches[icon.pk] = rank
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


def _ranked_ids(icons: list[Icon], terms: list[str], langs: list[str]) -> list[int]:
    """Icon ids matching ALL terms, ordered best-first.

    ``icons`` is the facet-filtered base set (capped); keyword matches
    outside it are discarded. Per term the best match rank of an icon
    counts; the icon's total rank is the worst (max) across terms. Ties
    break by order/slug.
    """
    icons_by_id = {icon.pk: icon for icon in icons}
    per_term: list[dict[int, int]] = []
    for term in terms:
        matches = _keyword_matches(term, langs)
        for icon_id, rank in _slug_matches(term, icons).items():
            if icon_id not in matches or rank < matches[icon_id]:
                matches[icon_id] = rank
        if not matches:
            # Typo tolerance only when the term matches nothing exactly.
            matches = _fuzzy_matches(term, langs)
        matches = {
            icon_id: rank for icon_id, rank in matches.items() if icon_id in icons_by_id
        }
        if not matches:
            return []
        per_term.append(matches)
    common = set.intersection(*(set(m) for m in per_term))
    return sorted(
        common,
        key=lambda icon_id: (
            max(m[icon_id] for m in per_term),
            icons_by_id[icon_id].order,
            icons_by_id[icon_id].slug,
        ),
    )


def _search(query: IconsQuery) -> list[Icon]:
    """Resolve one icons request to a page of icons."""
    base = (
        Icon.objects.filter(is_active=True)
        .select_related(
            "pack",
            "category__parent",
            "symbol_detailed",
            "symbol_simple",
            "symbol_mono",
        )
        .prefetch_related("curated_lists")
        .order_by("order", "slug")
    )
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
    terms = [
        folded for folded in (fold_keyword(t) for t in query.search.split()) if folded
    ]
    if not terms:
        return list(base[query.offset : query.offset + query.limit])
    icons = list(base[:_FACET_LIMIT])
    langs = _match_locales(query.lang)
    ids = _ranked_ids(icons, terms, langs)
    page = ids[query.offset : query.offset + query.limit]
    icons_by_id = {icon.pk: icon for icon in icons}
    return [icons_by_id[icon_id] for icon_id in page]


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
            for cl in icon.curated_lists.all()
        ),
        urls=IconUrls.model_validate(urls) if urls else None,
    )


def _last_modified() -> tuple[str, object]:
    """(http-date string, latest datetime) across registry tables."""
    latest = None
    for model in (Icon, IconKeyword, Symbol):
        modified = model.objects.aggregate(m=Max("modified"))["m"]
        if modified is not None and (latest is None or modified > latest):
            latest = modified
    return http_date(latest.timestamp()) if latest else http_date(0), latest


def _etag(request: HttpRequest, query: IconsQuery) -> str:
    """Content ETag over the registry state + request keys.

    Keyed on table modification maxima (re-imports and asset
    replacements invalidate), a content hash of the emoji taxonomy
    (localized names carry no timestamp, like the huts endpoint), and
    the query parameters + API version (versioned 304 safety).
    """
    parts = [
        # Per-table maxima (NOT the global max): a change in any single
        # table must invalidate, even when another table is newer.
        str(Icon.objects.aggregate(m=Max("modified"))["m"]),
        str(IconKeyword.objects.aggregate(m=Max("modified"))["m"]),
        str(Symbol.objects.aggregate(m=Max("modified"))["m"]),
        # Curated-list membership is timestamped via the explicit through
        # model, so admin curation invalidates immediately.
        str(IconCuratedList.objects.aggregate(m=Max("modified"))["m"]),
        str(IconCuratedListEntry.objects.aggregate(m=Max("modified"))["m"]),
        repr(
            list(SymbolCollection.objects.order_by("pk").values_list("slug", "extra"))
        ),
        json.dumps(
            list(
                Category.objects.filter(
                    Q(parent__slug="emoji") | Q(parent__parent__slug="emoji")
                ).values_list("id", "slug", "name", "i18n")
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
        etag = _etag(request, query)
        last_modified = _last_modified()[0]
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

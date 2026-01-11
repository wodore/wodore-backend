"""
API endpoints for GeoPlace search and queries.
"""

from enum import Enum
from typing import Any

from ninja import Query, Router
from ninja.decorators import decorate_view

from django.conf import settings
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Point
from django.contrib.gis.measure import D
from django.contrib.postgres.aggregates import JSONBAgg
from django.db.models import F, Q
from django.db.models.functions import JSONObject
from django.http import HttpRequest, HttpResponse
from django.views.decorators.cache import cache_control

from server.apps.translations import LanguageParam, activate, with_language_param

from .models import GeoPlace

router = Router(tags=["geoplaces"])


class IncludeModeEnum(str, Enum):
    """Include mode enum for search endpoint - controls level of detail."""

    no = "no"
    slug = "slug"
    all = "all"


@router.get(
    "search",
    response=list[dict],
    exclude_unset=True,
    operation_id="search_geoplaces",
)
@decorate_view(cache_control(max_age=60))
@with_language_param("lang")
def search_geoplaces(
    request: HttpRequest,
    response: HttpResponse,
    lang: LanguageParam,
    q: str = Query(
        ...,
        description="Search query string to match against place names in all languages",
        example="Matterhorn",
    ),
    limit: int = Query(15, description="Maximum number of results to return"),
    offset: int = Query(0, description="Number of results to skip for pagination"),
    types: list[str] | None = Query(
        None,
        description="Filter by place type slugs (e.g., 'peak', 'pass', 'lake'). Use 'parent.child' format for child categories.",
    ),
    categories: list[str] | None = Query(
        None,
        description="Filter by parent category slugs (e.g., 'terrain', 'transport')",
    ),
    countries: list[str] | None = Query(
        None,
        description="Filter by country codes (e.g., 'CH', 'FR', 'IT')",
    ),
    threshold: float = Query(
        0.2,
        description="Minimum similarity score (0.0-1.0). Lower values return more results but with lower relevance. Recommended: 0.1 for fuzzy matching, 0.3 for stricter matching.",
    ),
    min_importance: int = Query(
        0,
        description="Minimum importance score (0-100). Higher values filter for more prominent places.",
    ),
    include_place_type: IncludeModeEnum = Query(
        IncludeModeEnum.all,
        description="Include place type information: 'no' excludes field, 'slug' returns type slug only, 'all' returns full type details with name and description",
    ),
    include_sources: IncludeModeEnum = Query(
        IncludeModeEnum.no,
        description="Include data sources: 'no' excludes field, 'slug' returns source slugs only, 'all' returns full source details with name and logo",
    ),
) -> Any:
    """Search for geographic places using fuzzy text search across all language fields."""
    activate(lang)

    # Start with active, public places - use only() for better performance
    queryset = GeoPlace.objects.filter(is_active=True, is_public=True)

    # Filter by importance
    if min_importance > 0:
        queryset = queryset.filter(importance__gte=min_importance)

    # Filter by countries
    if countries:
        queryset = queryset.filter(country_code__in=[c.upper() for c in countries])

    # Filter by parent categories
    if categories:
        queryset = queryset.filter(place_type__parent__slug__in=categories)

    # Filter by place types
    if types:
        type_conditions = Q()
        for type_slug in types:
            # Handle parent.child format
            if "." in type_slug:
                parent_slug, child_slug = type_slug.split(".", 1)
                type_conditions |= Q(
                    place_type__parent__slug=parent_slug, place_type__slug=child_slug
                )
            else:
                # Could be either parent or child category
                type_conditions |= Q(place_type__slug=type_slug) | Q(
                    place_type__parent__slug=type_slug
                )
        queryset = queryset.filter(type_conditions)

    # Only select_related if we need the place_type data
    if include_place_type != IncludeModeEnum.no:
        queryset = queryset.select_related("place_type", "place_type__parent")

    # Add source annotations based on include_sources parameter
    if include_sources == IncludeModeEnum.slug:
        queryset = queryset.annotate(
            source_slugs=JSONBAgg(F("source_set__slug"), distinct=True),
            source_ids=JSONBAgg(F("source_associations__source_id"), distinct=True),
        )
    elif include_sources == IncludeModeEnum.all:
        queryset = queryset.annotate(
            sources_data=JSONBAgg(
                JSONObject(
                    slug="source_set__slug",
                    name="source_set__name_i18n",
                    logo="source_set__logo",
                    source_id="source_associations__source_id",
                ),
                distinct=True,
            )
        )

    # Fuzzy search using trigram similarity
    # Use similarity on name field (searches across all i18n variants via modeltrans)
    from django.contrib.postgres.search import TrigramSimilarity

    queryset = (
        queryset.annotate(similarity=TrigramSimilarity("name", q))
        .filter(similarity__gte=threshold)
        .order_by("-importance", "-similarity")[offset : offset + limit]
    )

    # Build simplified response
    results = []
    media_url = settings.MEDIA_URL
    if not media_url.startswith("http"):
        media_url = request.build_absolute_uri(media_url)

    for place in queryset:
        result = {
            "name": place.name_i18n,
            "country_code": str(place.country_code) if place.country_code else None,
            "id": place.id,
            "elevation": place.elevation,
            "importance": place.importance,
            "location": {
                "lat": place.location.y if place.location else None,
                "lon": place.location.x if place.location else None,
            },
        }

        # Include score
        result["score"] = place.similarity

        # Include place_type based on parameter
        if include_place_type == IncludeModeEnum.slug:
            result["place_type"] = place.place_type.slug if place.place_type else None
        elif include_place_type == IncludeModeEnum.all:
            if place.place_type:
                result["place_type"] = {
                    "slug": place.place_type.slug,
                    "name": place.place_type.name_i18n,
                    "description": place.place_type.description_i18n,
                    "icon": f"{media_url}{place.place_type.symbol_mono}"
                    if place.place_type.symbol_mono
                    else None,
                    "symbol": f"{media_url}{place.place_type.symbol_detailed}"
                    if place.place_type.symbol_detailed
                    else None,
                    "symbol_simple": f"{media_url}{place.place_type.symbol_simple}"
                    if place.place_type.symbol_simple
                    else None,
                }
            else:
                result["place_type"] = None

        # Include sources based on parameter
        if include_sources == IncludeModeEnum.slug:
            slugs = [slug for slug in (place.source_slugs or []) if slug is not None]
            ids = [sid for sid in (place.source_ids or []) if sid is not None]
            # Create list of dicts with source and source_id
            sources_list = []
            for i, slug in enumerate(slugs):
                source_item = {"source": slug}
                if i < len(ids) and ids[i]:
                    source_item["source_id"] = ids[i]
                sources_list.append(source_item)
            result["sources"] = sources_list
        elif include_sources == IncludeModeEnum.all:
            sources = []
            for src in place.sources_data or []:
                if src.get("slug") is not None:
                    source_item = {
                        "source": {
                            "slug": src["slug"],
                            "name": src.get("name"),
                            "logo": f"{media_url}{src['logo']}"
                            if src.get("logo")
                            else None,
                        }
                    }
                    if src.get("source_id"):
                        source_item["source_id"] = src["source_id"]
                    sources.append(source_item)
            result["sources"] = sources

        results.append(result)

    return results


@router.get(
    "nearby",
    response=list[dict],
    exclude_unset=True,
    operation_id="nearby_geoplaces",
)
@decorate_view(cache_control(max_age=60))
@with_language_param("lang")
def nearby_geoplaces(
    request: HttpRequest,
    response: HttpResponse,
    lang: LanguageParam,
    lat: float = Query(..., description="Latitude coordinate", example=46.0342),
    lon: float = Query(..., description="Longitude coordinate", example=7.6488),
    radius: float = Query(
        10000, description="Search radius in meters (default: 10000 = 10km)"
    ),
    limit: int = Query(20, description="Maximum number of results"),
    offset: int = Query(0, description="Number of results to skip for pagination"),
    types: list[str] | None = Query(
        None,
        description="Filter by place type slugs (e.g., 'peak', 'pass'). Use 'parent.child' format for child categories.",
    ),
    categories: list[str] | None = Query(
        None, description="Filter by parent category slugs"
    ),
    min_importance: int = Query(0, description="Minimum importance score (0-100)"),
    include_place_type: IncludeModeEnum = Query(
        IncludeModeEnum.all,
        description="Include place type information: 'no' excludes field, 'slug' returns type slug only, 'all' returns full type details with name and description",
    ),
    include_sources: IncludeModeEnum = Query(
        IncludeModeEnum.no,
        description="Include data sources: 'no' excludes field, 'slug' returns source slugs only, 'all' returns full source details with name and logo",
    ),
) -> Any:
    """Find places near coordinates within a radius, ordered by distance."""
    activate(lang)

    point = Point(lon, lat, srid=4326)

    # Start with active, public places within radius
    queryset = GeoPlace.objects.filter(
        is_active=True,
        is_public=True,
        location__distance_lte=(point, D(m=radius)),
    )

    # Filter by importance
    if min_importance > 0:
        queryset = queryset.filter(importance__gte=min_importance)

    # Filter by parent categories
    if categories:
        queryset = queryset.filter(place_type__parent__slug__in=categories)

    # Filter by place types
    if types:
        type_conditions = Q()
        for type_slug in types:
            if "." in type_slug:
                parent_slug, child_slug = type_slug.split(".", 1)
                type_conditions |= Q(
                    place_type__parent__slug=parent_slug, place_type__slug=child_slug
                )
            else:
                type_conditions |= Q(place_type__slug=type_slug) | Q(
                    place_type__parent__slug=type_slug
                )
        queryset = queryset.filter(type_conditions)

    # Only select_related if we need the place_type data
    if include_place_type != IncludeModeEnum.no:
        queryset = queryset.select_related("place_type", "place_type__parent")

    # Add source annotations based on include_sources parameter
    if include_sources == IncludeModeEnum.slug:
        queryset = queryset.annotate(
            source_slugs=JSONBAgg(F("source_set__slug"), distinct=True),
            source_ids=JSONBAgg(F("source_associations__source_id"), distinct=True),
        )
    elif include_sources == IncludeModeEnum.all:
        queryset = queryset.annotate(
            sources_data=JSONBAgg(
                JSONObject(
                    slug="source_set__slug",
                    name="source_set__name_i18n",
                    logo="source_set__logo",
                    source_id="source_associations__source_id",
                ),
                distinct=True,
            )
        )

    # Annotate with distance and order by it
    queryset = queryset.annotate(distance=Distance("location", point)).order_by(
        "distance"
    )[offset : offset + limit]

    # Build simplified response
    results = []
    media_url = settings.MEDIA_URL
    if not media_url.startswith("http"):
        media_url = request.build_absolute_uri(media_url)

    for place in queryset:
        # Distance annotation is a Distance object - convert to meters
        distance_m = (
            place.distance.m if hasattr(place.distance, "m") else place.distance
        )

        result = {
            "name": place.name_i18n,
            "country_code": str(place.country_code) if place.country_code else None,
            "id": place.id,
            "elevation": place.elevation,
            "importance": place.importance,
            "location": {
                "lat": place.location.y if place.location else None,
                "lon": place.location.x if place.location else None,
            },
            "distance": round(distance_m, 2) if distance_m else None,
        }

        # Include place_type based on parameter
        if include_place_type == IncludeModeEnum.slug:
            result["place_type"] = place.place_type.slug if place.place_type else None
        elif include_place_type == IncludeModeEnum.all:
            if place.place_type:
                result["place_type"] = {
                    "slug": place.place_type.slug,
                    "name": place.place_type.name_i18n,
                    "description": place.place_type.description_i18n,
                    "icon": f"{media_url}{place.place_type.symbol_mono}"
                    if place.place_type.symbol_mono
                    else None,
                    "symbol": f"{media_url}{place.place_type.symbol_detailed}"
                    if place.place_type.symbol_detailed
                    else None,
                    "symbol_simple": f"{media_url}{place.place_type.symbol_simple}"
                    if place.place_type.symbol_simple
                    else None,
                }
            else:
                result["place_type"] = None

        # Include sources based on parameter
        if include_sources == IncludeModeEnum.slug:
            slugs = [slug for slug in (place.source_slugs or []) if slug is not None]
            ids = [sid for sid in (place.source_ids or []) if sid is not None]
            # Create list of dicts with source and source_id
            sources_list = []
            for i, slug in enumerate(slugs):
                source_item = {"source": slug}
                if i < len(ids) and ids[i]:
                    source_item["source_id"] = ids[i]
                sources_list.append(source_item)
            result["sources"] = sources_list
        elif include_sources == IncludeModeEnum.all:
            sources = []
            for src in place.sources_data or []:
                if src.get("slug") is not None:
                    source_item = {
                        "source": {
                            "slug": src["slug"],
                            "name": src.get("name"),
                            "logo": f"{media_url}{src['logo']}"
                            if src.get("logo")
                            else None,
                        }
                    }
                    if src.get("source_id"):
                        source_item["source_id"] = src["source_id"]
                    sources.append(source_item)
            result["sources"] = sources

        results.append(result)

    return results

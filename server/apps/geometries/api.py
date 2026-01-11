"""
API endpoints for GeoPlace search and queries.
"""

from typing import Any

from ninja import Query, Router

from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Point
from django.contrib.gis.measure import D
from django.db.models import Q
from django.http import HttpRequest, HttpResponse

from .models import GeoPlace
from .schemas import GeoPlaceNearbySchema, GeoPlaceSearchSchema

router = Router(tags=["geoplaces"])


@router.get(
    "search",
    response=list[GeoPlaceSearchSchema],
    exclude_unset=True,
    operation_id="search_geoplaces",
)
def search_geoplaces(
    request: HttpRequest,
    response: HttpResponse,
    q: str = Query(
        ...,
        description="Search query string to match against place names",
        example="Matterhorn",
    ),
    limit: int = Query(
        15, description="Maximum number of results to return (default: 15)"
    ),
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
        0.1,
        description="Minimum similarity score (0.0-1.0). Lower values return more results but with lower relevance. Recommended: 0.1 for fuzzy matching, 0.3 for stricter matching.",
        example=0.3,
    ),
    min_importance: int = Query(
        0,
        description="Minimum importance score (0-100). Higher values filter for more prominent places.",
    ),
) -> Any:
    """
    Search for geographic places using fuzzy text search.

    Returns results ordered by importance and relevance. Searches across
    all language fields (name translations) and uses trigram similarity
    for fuzzy matching.
    """
    # Start with active, public places
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

    # Fuzzy search using trigram similarity
    # Use similarity on name field (searches across all i18n variants via modeltrans)
    from django.contrib.postgres.search import TrigramSimilarity

    queryset = (
        queryset.annotate(similarity=TrigramSimilarity("name", q))
        .filter(similarity__gte=threshold)
        .order_by("-importance", "-similarity")[:limit]
    )

    return list(queryset.select_related("place_type", "place_type__parent"))


@router.get(
    "nearby",
    response=list[GeoPlaceNearbySchema],
    exclude_unset=True,
    operation_id="nearby_geoplaces",
)
def nearby_geoplaces(
    request: HttpRequest,
    response: HttpResponse,
    lat: float = Query(..., description="Latitude coordinate", example=46.0342),
    lon: float = Query(..., description="Longitude coordinate", example=7.6488),
    radius: float = Query(
        10000, description="Search radius in meters (default: 10000 = 10km)"
    ),
    limit: int = Query(20, description="Maximum number of results (default: 20)"),
    types: list[str] | None = Query(
        None,
        description="Filter by place type slugs (e.g., 'peak', 'pass'). Use 'parent.child' format for child categories.",
    ),
    categories: list[str] | None = Query(
        None, description="Filter by parent category slugs"
    ),
    min_importance: int = Query(0, description="Minimum importance score (0-100)"),
) -> Any:
    """
    Find places near coordinates within a radius.

    Returns places ordered by distance from the given coordinates.
    Includes distance in meters for each result.
    """
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

    # Annotate with distance and order by it
    queryset = (
        queryset.annotate(distance=Distance("location", point))
        .order_by("distance")[:limit]
        .select_related("place_type", "place_type__parent")
    )

    # Convert distance to meters (Distance returns in default units)
    results = []
    for place in queryset:
        # Distance annotation is a Distance object - convert to meters
        distance_m = (
            place.distance.m if hasattr(place.distance, "m") else place.distance
        )
        result_dict = {
            "id": place.id,
            "name": place.name_i18n,
            "place_type": place.place_type,
            "country_code": place.country_code,
            "elevation": place.elevation,
            "importance": place.importance,
            "latitude": place.location.y if place.location else None,
            "longitude": place.location.x if place.location else None,
            "distance": round(distance_m, 2) if distance_m else None,
        }
        results.append(result_dict)

    return results

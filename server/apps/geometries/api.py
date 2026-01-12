"""
API endpoints for GeoPlace search and queries.
"""

from enum import Enum
from typing import Any

from django.contrib.gis.geos import Point
from ninja import Query, Router
from ninja.decorators import decorate_view

from django.conf import settings
from django.contrib.gis.db.models import PointField
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.measure import D
from django.contrib.postgres.aggregates import JSONBAgg
from django.contrib.postgres.search import (
    SearchQuery,
    SearchRank,
    SearchVector,
    TrigramSimilarity,
    TrigramWordSimilarity,
)
from django.db.models import F, Q
from django.db.models import (
    Case,
    CharField,
    ExpressionWrapper,
    FloatField,
    Func,
    Value,
    When,
    Window,
)
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast, Coalesce, Greatest, Lower, RowNumber
from django.db.models.functions import JSONObject
from django.http import HttpRequest, HttpResponse
from django.views.decorators.cache import cache_control

from server.apps.translations import LanguageParam, activate, with_language_param

from .models import GeoPlace
from .schemas import (
    GeoPlaceNearbySchema,
    GeoPlaceSearchSchema,
)
from server.apps.organizations.schema import (
    OrganizationSourceIdDetailSchema,
    OrganizationSourceIdSlugSchema,
)

router = Router(tags=["geometries"])


class IncludeModeEnum(str, Enum):
    """Include mode enum for search endpoint - controls level of detail."""

    no = "no"
    slug = "slug"
    all = "all"


@router.get(
    "search",
    response=list[GeoPlaceSearchSchema],
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
    deduplicate: bool = Query(
        False,
        description="Remove near-identical places that share a name and a very close location before pagination.",
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
    default_language = settings.LANGUAGE_CODE
    requested_language = lang
    translated_name = None
    if requested_language != default_language:
        translated_name = Cast(
            KeyTextTransform(f"name_{requested_language}", "i18n"),
            output_field=CharField(),
        )
        primary_similarity = Coalesce(
            Greatest(
                TrigramSimilarity(translated_name, q),
                TrigramWordSimilarity(translated_name, Value(q)),
            ),
            Value(0.0),
        )
    else:
        primary_similarity = Coalesce(
            Greatest(
                TrigramSimilarity("name", q),
                TrigramWordSimilarity("name", Value(q)),
            ),
            Value(0.0),
        )
    translation_languages = [
        code
        for code in getattr(settings, "LANGUAGE_CODES", [])
        if code and code not in {default_language, requested_language}
    ]
    translation_similarity_exprs = [
        Coalesce(
            Greatest(
                TrigramSimilarity(
                    Cast(
                        KeyTextTransform(f"name_{lang}", "i18n"),
                        output_field=CharField(),
                    ),
                    q,
                ),
                TrigramWordSimilarity(
                    Cast(
                        KeyTextTransform(f"name_{lang}", "i18n"),
                        output_field=CharField(),
                    ),
                    Value(q),
                ),
            ),
            Value(0.0),
        )
        for lang in translation_languages
    ]
    if translation_similarity_exprs:
        best_translation_similarity = Greatest(*translation_similarity_exprs)
    else:
        best_translation_similarity = Value(0.0)
    translation_boost = ExpressionWrapper(
        Value(0.6) * best_translation_similarity,
        output_field=FloatField(),
    )
    similarity_expr = ExpressionWrapper(
        Greatest(primary_similarity, translation_boost),
        output_field=FloatField(),
    )
    stripped_query = q.strip()
    tokens = [token for token in stripped_query.split() if token]
    if len(tokens) > 1:
        search_vector = SearchVector("name", weight="A", config="simple")
        if translated_name is not None:
            search_vector = search_vector + SearchVector(
                translated_name, weight="A", config="simple"
            )
        search_query = SearchQuery(stripped_query, search_type="plain", config="simple")
        fts_rank = SearchRank(search_vector, search_query)
        token_cases = [
            Case(
                When(name__icontains=token, then=Value(1.0)),
                default=Value(0.0),
                output_field=FloatField(),
            )
            for token in tokens[:3]
        ]
        token_match = ExpressionWrapper(
            sum(token_cases) / Value(len(token_cases)),
            output_field=FloatField(),
        )
    else:
        fts_rank = Value(0.0)
        token_match = Value(0.0)
    if translated_name is not None:
        translated_prefix_lookup = {f"i18n__name_{requested_language}__istartswith": q}
        prefix_match = Greatest(
            Case(
                When(name__istartswith=q, then=Value(1.0)),
                default=Value(0.0),
                output_field=FloatField(),
            ),
            Case(
                When(**translated_prefix_lookup, then=Value(1.0)),
                default=Value(0.0),
                output_field=FloatField(),
            ),
        )
    else:
        prefix_match = Case(
            When(name__istartswith=q, then=Value(1.0)),
            default=Value(0.0),
            output_field=FloatField(),
        )
    normalized_importance = Case(
        When(importance__lt=0, then=Value(0.0)),
        When(importance__gt=100, then=Value(1.0)),
        default=Coalesce(F("importance"), Value(0)) / Value(100.0),
        output_field=FloatField(),
    )
    rank_score = ExpressionWrapper(
        Value(0.8) * similarity_expr + Value(0.2) * normalized_importance,
        output_field=FloatField(),
    )

    queryset = queryset.annotate(
        similarity=similarity_expr,
        rank_score=rank_score,
        prefix_match=prefix_match,
        fts_rank=fts_rank,
        token_match=token_match,
    ).filter(similarity__gte=threshold)

    if deduplicate:
        grid_size = Value(0.00005)
        snapped_location = Func(
            F("location"),
            grid_size,
            grid_size,
            function="ST_SnapToGrid",
            output_field=PointField(),
        )
        normalized_name = Lower(F("name"))
        duplicate_rank = Window(
            expression=RowNumber(),
            partition_by=[
                snapped_location,
                normalized_name,
                F("place_type"),
                F("country_code"),
            ],
            order_by=[
                F("prefix_match").desc(nulls_last=True),
                F("token_match").desc(nulls_last=True),
                F("rank_score").desc(nulls_last=True),
                F("fts_rank").desc(nulls_last=True),
                F("similarity").desc(nulls_last=True),
                F("id").asc(),
            ],
        )
        queryset = queryset.annotate(duplicate_rank=duplicate_rank).filter(
            duplicate_rank=1
        )

    queryset = queryset.order_by(
        "-prefix_match",
        "-token_match",
        "-rank_score",
        "-fts_rank",
        "-similarity",
    )[offset : offset + limit]

    # Build structured response using schemas
    results = []
    media_url = settings.MEDIA_URL
    if not media_url.startswith("http"):
        media_url = request.build_absolute_uri(media_url)

    for place in queryset:
        # Build base result
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
            "score": place.rank_score,
        }

        # Include place_type based on parameter
        if include_place_type == IncludeModeEnum.slug:
            result["place_type"] = place.place_type.slug if place.place_type else None
        elif include_place_type == IncludeModeEnum.all:
            if place.place_type:
                # Build category schema manually
                category_data = {
                    "slug": place.place_type.slug,
                    "name": place.place_type.name_i18n,
                    "description": place.place_type.description_i18n,
                }
                # Add symbol if requested
                if (
                    place.place_type.symbol_simple
                    or place.place_type.symbol_detailed
                    or place.place_type.symbol_mono
                ):
                    symbol_data = {}
                    if place.place_type.symbol_simple:
                        symbol_data["simple"] = (
                            f"{media_url}{place.place_type.symbol_simple}"
                        )
                    if place.place_type.symbol_detailed:
                        symbol_data["detailed"] = (
                            f"{media_url}{place.place_type.symbol_detailed}"
                        )
                    if place.place_type.symbol_mono:
                        symbol_data["mono"] = (
                            f"{media_url}{place.place_type.symbol_mono}"
                        )
                    category_data["symbol"] = symbol_data
                result["place_type"] = category_data
            else:
                result["place_type"] = None

        # Include sources based on parameter
        if include_sources == IncludeModeEnum.slug:
            slugs = [slug for slug in (place.source_slugs or []) if slug is not None]
            ids = [sid for sid in (place.source_ids or []) if sid is not None]
            sources_list = []
            for i, slug in enumerate(slugs):
                source_item = OrganizationSourceIdSlugSchema(
                    source=slug, source_id=ids[i] if i < len(ids) and ids[i] else None
                )
                sources_list.append(source_item.dict(exclude_unset=True))
            if sources_list:
                result["sources"] = sources_list
        elif include_sources == IncludeModeEnum.all:
            sources = []
            for src in place.sources_data or []:
                if src.get("slug") is not None:
                    # Create a dict-based organization object for the schema
                    org_data = {
                        "slug": src["slug"],
                        "name": src.get("name"),
                        "logo": (
                            f"{media_url}{src['logo']}" if src.get("logo") else None
                        ),
                    }
                    source_item = OrganizationSourceIdDetailSchema(
                        source=org_data,
                        source_id=src.get("source_id"),
                    )
                    sources.append(
                        source_item.dict(
                            exclude_unset=True, exclude={"source": {"logo"}}
                        )
                    )
            if sources:
                result["sources"] = sources

        results.append(result)

    return [GeoPlaceSearchSchema(**result) for result in results]


@router.get(
    "nearby",
    response=list[GeoPlaceNearbySchema],
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

    # Build structured response using schemas
    results = []
    media_url = settings.MEDIA_URL
    if not media_url.startswith("http"):
        media_url = request.build_absolute_uri(media_url)

    for place in queryset:
        # Distance annotation is a Distance object - convert to meters
        distance_m = (
            place.distance.m if hasattr(place.distance, "m") else place.distance
        )

        # Build base result
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
                # Build category schema manually
                category_data = {
                    "slug": place.place_type.slug,
                    "name": place.place_type.name_i18n,
                    "description": place.place_type.description_i18n,
                }
                # Add symbol if requested
                if (
                    place.place_type.symbol_simple
                    or place.place_type.symbol_detailed
                    or place.place_type.symbol_mono
                ):
                    symbol_data = {}
                    if place.place_type.symbol_simple:
                        symbol_data["simple"] = (
                            f"{media_url}{place.place_type.symbol_simple}"
                        )
                    if place.place_type.symbol_detailed:
                        symbol_data["detailed"] = (
                            f"{media_url}{place.place_type.symbol_detailed}"
                        )
                    if place.place_type.symbol_mono:
                        symbol_data["mono"] = (
                            f"{media_url}{place.place_type.symbol_mono}"
                        )
                    category_data["symbol"] = symbol_data
                result["place_type"] = category_data
            else:
                result["place_type"] = None

        # Include sources based on parameter
        if include_sources == IncludeModeEnum.slug:
            slugs = [slug for slug in (place.source_slugs or []) if slug is not None]
            ids = [sid for sid in (place.source_ids or []) if sid is not None]
            sources_list = []
            for i, slug in enumerate(slugs):
                source_item = OrganizationSourceIdSlugSchema(
                    source=slug, source_id=ids[i] if i < len(ids) and ids[i] else None
                )
                sources_list.append(source_item.dict(exclude_unset=True))
            if sources_list:
                result["sources"] = sources_list
        elif include_sources == IncludeModeEnum.all:
            sources = []
            for src in place.sources_data or []:
                if src.get("slug") is not None:
                    # Create a dict-based organization object for the schema
                    org_data = {
                        "slug": src["slug"],
                        "name": src.get("name"),
                        "logo": (
                            f"{media_url}{src['logo']}" if src.get("logo") else None
                        ),
                    }
                    source_item = OrganizationSourceIdDetailSchema(
                        source=org_data,
                        source_id=src.get("source_id"),
                    )
                    sources.append(
                        source_item.dict(
                            exclude_unset=True, exclude={"source": {"logo"}}
                        )
                    )
            if sources:
                result["sources"] = sources

        results.append(result)

    return [GeoPlaceNearbySchema(**result) for result in results]

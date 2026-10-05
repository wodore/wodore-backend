"""GeoPlace search and query endpoints on dmr."""

import pydantic
from dmr import Path, Query, modify
from dmr.routing import path
from pydantic import Field

from django.views.decorators.cache import cache_page

from server.apps.api.controller import ApiController, cache_headers, raise_not_found
from server.apps.api.projection import field_selected, project_fields
from server.apps.api.query import BboxQuery, bbox_polygon, sparse_fields_query
from server.apps.geometries.presenters import (
    annotate_sources,
    apply_type_filters,
    base_result,
    build_categories_data,
    build_sources,
    prefetch_categories,
)
from server.apps.geometries.schemas import CategoryPlaceTypeSchema as CategorySchema
from server.apps.organizations.schema import OrganizationSourceIdSlugSchema
from server.apps.translations import LanguageQuery

from .models import GeoPlace
from .schemas import (
    AmenitySchema,
    GeoPlaceNearbySchema,
    GeoPlaceSearchSchema,
)

__all__ = ["paths"]


GeoPlaceFields = sparse_fields_query(
    places=GeoPlaceSearchSchema,
    categories=CategorySchema,
    sources=OrganizationSourceIdSlugSchema,
)


class _GeoSearchQuery(LanguageQuery, GeoPlaceFields):
    """Query parameters shared by search and nearby."""

    types: list[str] | None = Field(
        None,
        description=(
            "Filter by category slugs (e.g., 'peak', 'pass', 'lake'). Use "
            "'parent.child' format for child categories."
        ),
    )
    categories: list[str] | None = Field(
        None,
        description=("Filter by parent category slugs (e.g., 'terrain', 'transport')"),
    )


class GeoSearchQuery(_GeoSearchQuery, BboxQuery):
    """Query parameters for the place search endpoint."""

    q: str = Field(
        description="Search query string to match against place names in all languages",
        json_schema_extra={"example": "Matterhorn"},
    )
    limit: int = Field(15, description="Maximum number of results to return")
    offset: int = Field(0, description="Number of results to skip for pagination")
    countries: list[str] | None = Field(
        None,
        description="Filter by country codes (e.g., 'CH', 'FR', 'IT')",
    )
    threshold: float = Field(
        0.2,
        description=(
            "Minimum similarity score (0.0-1.0). Lower values return more "
            "results but with lower relevance. Recommended: 0.1 for fuzzy "
            "matching, 0.3 for stricter matching."
        ),
    )
    min_importance: int = Field(
        0,
        description=(
            "Minimum importance score (0-100). Higher values filter for "
            "more prominent places."
        ),
    )
    deduplicate: bool = Field(
        False,
        description=(
            "Remove near-identical places that share a name and a very "
            "close location before pagination."
        ),
    )


class GeoNearbyQuery(_GeoSearchQuery):
    """Query parameters for the nearby endpoint."""

    lat: float = Field(
        description="Latitude coordinate", json_schema_extra={"example": 46.0342}
    )
    lon: float = Field(
        description="Longitude coordinate", json_schema_extra={"example": 7.6488}
    )
    radius: float = Field(
        10000,
        description="Search radius in meters (default: 10000 = 10km)",
    )
    limit: int = Field(20, description="Maximum number of results")
    offset: int = Field(0, description="Number of results to skip for pagination")
    min_importance: int = Field(0, description="Minimum importance score (0-100)")


class AmenityQuery(LanguageQuery, GeoPlaceFields):
    """Query parameters for the amenity detail endpoint."""


class AmenityPath(pydantic.BaseModel):
    """Amenity place id path parameter."""

    place_id: int = Field(description="GeoPlace id")


# ---------------------------------------------------------------------------
# Controllers
# ---------------------------------------------------------------------------


class OverlayCategoriesController(ApiController):
    """Overlay categories for map tile filtering."""

    @modify(
        operation_id="get_overlay_categories",
        headers=cache_headers(300),
    )
    def get(self) -> list[dict]:
        """List map overlay categories.

        Usable as overlay filters in vector tile requests; returns root-level categories that can be used as overlay filters
        in vector tile requests (via the `categories` parameter).
        """
        request = self.request
        from server.apps.categories.models import Category
        from server.apps.geometries.config.osm_categories import CATEGORY_REGISTRY

        category_slugs = [cat.category for cat in CATEGORY_REGISTRY]

        categories = (
            Category.objects.select_related(
                "parent",
                "symbol_detailed",
                "symbol_simple",
                "symbol_mono",
            )
            .filter(parent__isnull=True, slug__in=category_slugs, is_active=True)
            .order_by("order", "slug")
        )

        results = []
        for cat in categories:
            results.append(
                {
                    "slug": cat.slug,
                    "name": cat.name_i18n,  # noqa: WPS308  # modeltranslation
                    "description": cat.description_i18n or "",  # noqa: WPS308
                    "order": cat.order,
                    "level": cat.get_level(),
                    "parent": cat.parent.slug if cat.parent else None,
                    "identifier": cat.get_identifier(),
                    "color": cat.color,
                    "children": cat.has_children(),
                    "symbol_detailed": (
                        request.build_absolute_uri(cat.symbol_detailed.svg_file.url)
                        if cat.symbol_detailed and cat.symbol_detailed.svg_file
                        else None
                    ),
                    "symbol_simple": (
                        request.build_absolute_uri(cat.symbol_simple.svg_file.url)
                        if cat.symbol_simple and cat.symbol_simple.svg_file
                        else None
                    ),
                    "symbol_mono": (
                        request.build_absolute_uri(cat.symbol_mono.svg_file.url)
                        if cat.symbol_mono and cat.symbol_mono.svg_file
                        else None
                    ),
                }
            )

        return results


class GeoSearchController(ApiController):
    """Fuzzy place search across all language fields."""

    @modify(
        operation_id="search_geoplaces",
        headers=cache_headers(60),
    )
    def get(self, parsed_query: Query[GeoSearchQuery]) -> list[GeoPlaceSearchSchema]:
        """Search places.

        Fuzzy text search across all language fields. Performance optimizations:
        - Fast prefix matching using B-tree indexes (very fast)
        - Trigram similarity only when needed (slower)
        - Early exit if enough prefix matches found
        """
        from django.conf import settings
        from django.contrib.gis.db.models import PointField
        from django.contrib.gis.db.models.functions import (
            Distance,  # noqa: F401  # parity
        )
        from django.contrib.postgres.search import TrigramSimilarity
        from django.db.models import (
            Case,
            CharField,
            ExpressionWrapper,
            F,
            FloatField,
            Func,
            Value,
            When,
            Window,
        )
        from django.db.models.fields.json import KeyTextTransform
        from django.db.models.functions import (
            Cast,
            Coalesce,
            Greatest,
            Lower,
            RowNumber,
        )

        request = self.request
        query = parsed_query
        q = query.q.strip()
        if not q:
            return []

        default_language = settings.LANGUAGE_CODE

        queryset = GeoPlace.objects.filter(is_active=True, is_public=True).only(
            "id",
            "name",
            "i18n",
            "location",
            "elevation",
            "importance",
            "country_code",
        )

        if query.min_importance > 0:
            queryset = queryset.filter(importance__gte=query.min_importance)
        if query.countries:
            queryset = queryset.filter(
                country_code__in=[c.upper() for c in query.countries]
            )

        queryset = apply_type_filters(queryset, query.types, query.categories)

        if query.bbox:
            queryset = queryset.filter(location__intersects=bbox_polygon(query.bbox))

        # Skip the DB cost when the field isn't in the selection
        # (the old include_X=no optimization, driven by fields[places]).
        # Readers disposition (OpenSpec §4.3, benchmarked N=50 via
        # scripts/benchmark/readers_hot_paths.py): parity at best
        # (p50 +1.3%, p95 worse) and the conversion is override-only —
        # the projection resolves symbol URLs with the request context,
        # fields the wire schema does not declare. Hand-tuned on purpose.
        wants_categories = field_selected(query, "places", "categories")
        wants_sources = field_selected(query, "places", "sources")
        if wants_categories:
            queryset = prefetch_categories(queryset)
        if wants_sources:
            queryset = annotate_sources(queryset)

        # Fuzzy search using trigram similarity
        requested_language = query.lang
        translated_name = None

        if requested_language != default_language:
            translated_name = Cast(
                KeyTextTransform(f"name_{requested_language}", "i18n"),
                output_field=CharField(),
            )
            primary_similarity = TrigramSimilarity(translated_name, q)
        else:
            primary_similarity = TrigramSimilarity("name", q)

        translation_similarity = Value(0.0)
        if requested_language != default_language and translated_name is not None:
            translation_similarity = ExpressionWrapper(
                Value(0.3) * TrigramSimilarity("name", q),
                output_field=FloatField(),
            )

        similarity_expr = ExpressionWrapper(
            Greatest(primary_similarity, translation_similarity),
            output_field=FloatField(),
        )

        tokens = [token for token in q.split() if token]

        if len(tokens) > 1:
            token_match_score = sum(
                1.0 for token in tokens[:3] if token.lower() in q.lower()
            ) / min(len(tokens), 3)
            token_match = Value(token_match_score, output_field=FloatField())
        else:
            token_match = Value(0.0)

        if translated_name is not None:
            prefix_match = Case(
                When(name__istartswith=q, then=Value(1.0)),
                When(
                    **{f"i18n__name_{requested_language}__istartswith": q},
                    then=Value(1.0),
                ),
                default=Value(0.0),
                output_field=FloatField(),
            )
        else:
            prefix_match = Case(
                When(name__istartswith=q, then=Value(1.0)),
                default=Value(0.0),
                output_field=FloatField(),
            )

        fts_rank = Value(0.0)
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
        ).filter(similarity__gte=query.threshold)

        if query.deduplicate:
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
        )[query.offset : query.offset + query.limit]

        results = []
        media_url = settings.MEDIA_URL
        if not media_url.startswith("http"):
            media_url = request.build_absolute_uri(media_url)

        for place in queryset:
            result = base_result(place, media_url)
            result["score"] = place.rank_score

            if wants_categories:
                result["categories"] = build_categories_data(place, request) or []
            if wants_sources:
                build_sources(result, place, media_url)
            results.append(result)

        return results


class GeoNearbyController(ApiController):
    """Places near coordinates, ordered by distance."""

    @modify(
        operation_id="nearby_geoplaces",
        headers=cache_headers(60),
    )
    def get(self, parsed_query: Query[GeoNearbyQuery]) -> list[GeoPlaceNearbySchema]:
        """Find places near coordinates, ordered by distance."""
        from django.conf import settings
        from django.contrib.gis.db.models.functions import Distance
        from django.contrib.gis.geos import Point
        from django.contrib.gis.measure import D

        request = self.request
        query = parsed_query

        point = Point(query.lon, query.lat, srid=4326)

        queryset = GeoPlace.objects.filter(
            is_active=True,
            is_public=True,
            location__distance_lte=(point, D(m=query.radius)),
        ).only(
            "id",
            "name",
            "i18n",
            "location",
            "elevation",
            "importance",
            "country_code",
        )

        if query.min_importance > 0:
            queryset = queryset.filter(importance__gte=query.min_importance)

        queryset = apply_type_filters(queryset, query.types, query.categories)

        # Skip the DB cost when the field isn't in the selection
        # Readers disposition (OpenSpec §4.3, benchmarked N=50 via
        # scripts/benchmark/readers_hot_paths.py): parity (p50 ±0%,
        # p95 worse) with an override-only conversion — hand-tuned on
        # purpose, same reasoning as search_geoplaces.
        wants_categories = field_selected(query, "places", "categories")
        wants_sources = field_selected(query, "places", "sources")
        if wants_categories:
            queryset = prefetch_categories(queryset)
        if wants_sources:
            queryset = annotate_sources(queryset)

        queryset = queryset.annotate(distance=Distance("location", point)).order_by(
            "distance"
        )[query.offset : query.offset + query.limit]

        results = []
        media_url = settings.MEDIA_URL
        if not media_url.startswith("http"):
            media_url = request.build_absolute_uri(media_url)

        for place in queryset:
            distance_m = (
                place.distance.m if hasattr(place.distance, "m") else place.distance
            )

            result = base_result(place, media_url)
            result["distance"] = round(distance_m, 2) if distance_m else None

            result["categories"] = build_categories_data(place, request) or []
            build_sources(result, place, media_url)
            results.append(
                project_fields(
                    result,
                    query,
                    "places",
                    {"categories": "categories", "sources": "sources"},
                )
            )

        return results


class AmenityController(ApiController):
    """Amenity place details (opening hours, websites, phones)."""

    @modify(
        operation_id="get_amenity",
        headers=cache_headers(60),
    )
    def get(
        self,
        parsed_path: Path[AmenityPath],
        parsed_query: Query[AmenityQuery],
    ) -> AmenitySchema:
        """Get an amenity place.

        Returns detailed information base GeoPlace fields plus amenity-specific information
        like operating status, opening hours, websites, and phone numbers.
        """

        request = self.request

        # Count the visit once we know the place exists (best-effort).
        from server.apps.visits.models import record_visit

        visit_place = (
            GeoPlace.objects.filter(id=parsed_path.place_id, is_active=True)
            .only("id")
            .first()
        )
        if visit_place is not None:
            record_visit(request, visit_place)

        try:
            place = (
                GeoPlace.objects.filter(
                    id=parsed_path.place_id,
                    is_active=True,
                    detail_type="amenity",
                )
                .select_related(
                    "amenity_detail",
                )
                .prefetch_related(
                    "categories",
                    "categories__parent",
                    "categories__symbol_detailed",
                    "categories__symbol_simple",
                    "categories__symbol_mono",
                )
                .only(
                    "id",
                    "name",
                    "i18n",
                    "description",
                    "location",
                    "elevation",
                    "importance",
                    "country_code",
                    "detail_type",
                    "review_status",
                )
                .get()
            )
        except GeoPlace.DoesNotExist:
            raise_not_found("Amenity not found")

        from django.conf import settings as dj_settings

        media_url = dj_settings.MEDIA_URL
        if not media_url.startswith("http"):
            media_url = request.build_absolute_uri(media_url)

        # Add source data (annotations must run on a queryset; the old
        # code annotated the instance which crashed for include_sources).
        if True:  # Always fetch — narrowing happens at projection
            from django.contrib.postgres.aggregates import JSONBAgg
            from django.db.models import F
            from django.db.models.functions import JSONObject

            if False:  # slug mode handled by projection
                annotated = (
                    GeoPlace.objects.filter(id=place.id)
                    .annotate(
                        source_slugs=JSONBAgg(F("source_set__slug"), distinct=True),
                        source_ids=JSONBAgg(
                            F("source_associations__source_id"), distinct=True
                        ),
                    )
                    .first()
                )
            else:
                annotated = (
                    GeoPlace.objects.filter(id=place.id)
                    .annotate(
                        sources_data=JSONBAgg(
                            JSONObject(
                                slug="source_set__slug",
                                name="source_set__name_i18n",
                                logo="source_set__logo",
                                source_id="source_associations__source_id",
                            ),
                            distinct=True,
                        ),
                    )
                    .first()
                )
            if annotated is not None:
                place.source_slugs = getattr(annotated, "source_slugs", None)
                place.source_ids = getattr(annotated, "source_ids", None)
                place.sources_data = getattr(annotated, "sources_data", None)

        result = base_result(place, media_url)
        result["description"] = place.description_i18n  # noqa: WPS308
        result["detail_type"] = place.detail_type
        result["review_status"] = place.review_status

        categories_data = build_categories_data(place, request)
        if categories_data:
            result["categories"] = categories_data

        if place.amenity_detail:
            result["amenity_detail"] = {
                "operating_status": place.amenity_detail.operating_status,
                "opening_months": place.amenity_detail.opening_months or {},
                "opening_hours": place.amenity_detail.opening_hours or {},
                "websites": place.amenity_detail.websites or [],
                "phones": place.amenity_detail.phones or [],
                "extra": place.amenity_detail.extra or {},
            }

        build_sources(result, place, media_url)

        return AmenitySchema(**result)


# Server-side page caching parity with the former ninja decorators
# (cache_page 300/60/60/60 + the per-endpoint Cache-Control headers).
# SEO/LLM surface (place meta + Markdown) and the generic static-map
# endpoint — appended after the core geo paths.
from . import api_map, api_seo  # end-of-module: avoids import cycle

paths = [
    *api_seo.paths,
    *api_map.paths,
    path(
        "places/overlays",
        cache_page(300)(OverlayCategoriesController.as_view()),
        name="get_overlay_categories",
    ),
    path(
        "places/search",
        cache_page(60)(GeoSearchController.as_view()),
        name="search_geoplaces",
    ),
    path(
        "places/nearby",
        cache_page(60)(GeoNearbyController.as_view()),
        name="nearby_geoplaces",
    ),
    path(
        "places/amenity/<int:place_id>",
        cache_page(60)(AmenityController.as_view()),
        name="get_amenity",
    ),
]

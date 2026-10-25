"""GeoPlace search and query endpoints on dmr."""

from typing import Any

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
    build_amenity_detail,
    build_categories_data,
    build_links_data,
    build_parties_data,
    build_sources,
    prefetch_categories,
    prefetch_links,
    prefetch_parties,
)
from server.apps.geometries.schemas import CategoryPlaceTypeSchema as CategorySchema
from server.apps.organizations.schema import OrganizationSourceIdSlugSchema
from server.apps.translations import LanguageQuery

from .converters import GeoPlaceSlugConverter  # noqa: F401  # registers <geoplace:slug>
from .models import GeoPlace
from .schemas import (
    GeoPlaceDetailSchema,
    GeoPlaceNearbySchema,
    GeoPlaceSearchSchema,
    LinkSchema,
    PartySchema,
)

__all__ = ["paths"]


GeoPlaceFields = sparse_fields_query(
    places=GeoPlaceSearchSchema,
    categories=CategorySchema,
    sources=OrganizationSourceIdSlugSchema,
    parties=PartySchema,
)

#: Detail-route fieldset registration: the top-level DTO is the detail
#: schema, so selection validity and required-keep (top-level *and*
#: nested) derive from the endpoint's declared members — never from
#: what a given row happens to carry (PR review finding on the former
#: hand-rolled narrowing).
PlaceDetailFields = sparse_fields_query(
    places=GeoPlaceDetailSchema,
    categories=CategorySchema,
    sources=OrganizationSourceIdSlugSchema,
    parties=PartySchema,
    links=LinkSchema,
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


class PlaceQuery(LanguageQuery, PlaceDetailFields):
    """Query parameters for the unified place detail endpoint."""


class PlacePath(pydantic.BaseModel):
    """Place slug path parameter (grammar-checked by the converter)."""

    slug: str = Field(description="GeoPlace slug")


# ---------------------------------------------------------------------------
# Controllers
# ---------------------------------------------------------------------------


class OverlayCategoriesController(ApiController):
    """Overlay categories for map tile filtering."""

    @modify(
        operation_id="get_overlay_categories",
        headers=cache_headers(300),
    )
    def get(self) -> list[dict[str, Any]]:
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
                "symbol_color",
                "symbol_primitive",
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
                    "symbol_color": (
                        request.build_absolute_uri(cat.symbol_color.svg_file.url)
                        if cat.symbol_color and cat.symbol_color.svg_file
                        else None
                    ),
                    "symbol_primitive": (
                        request.build_absolute_uri(cat.symbol_primitive.svg_file.url)
                        if cat.symbol_primitive and cat.symbol_primitive.svg_file
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
            "slug",
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
        wants_parties = field_selected(query, "places", "parties")
        if wants_categories:
            queryset = prefetch_categories(queryset)
        if wants_sources:
            queryset = annotate_sources(queryset)
        if wants_parties:
            queryset = prefetch_parties(queryset)

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
            # rank_score is a queryset annotation — django-stubs cannot
            # model .annotate() attributes.
            result["score"] = place.rank_score  # type: ignore  # annotated attr (rank_score)

            if wants_categories:
                result["categories"] = build_categories_data(place, request) or []
            if wants_sources:
                build_sources(result, place, media_url)
            if wants_parties:
                result["parties"] = build_parties_data(place, request) or []
            results.append(result)

        return results  # type: ignore  # serialized dicts match schema shape at runtime


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
            "slug",
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
        wants_parties = field_selected(query, "places", "parties")
        if wants_categories:
            queryset = prefetch_categories(queryset)
        if wants_sources:
            queryset = annotate_sources(queryset)
        if wants_parties:
            queryset = prefetch_parties(queryset)

        queryset = queryset.annotate(distance=Distance("location", point)).order_by(
            "distance"
        )[query.offset : query.offset + query.limit]

        results = []
        media_url = settings.MEDIA_URL
        if not media_url.startswith("http"):
            media_url = request.build_absolute_uri(media_url)

        for place in queryset:
            # distance is a queryset annotation (Distance("location", point))
            # — django-stubs cannot model .annotate() attributes.
            place_distance = place.distance  # type: ignore  # annotated attr (distance)
            distance_m = (
                place_distance.m if hasattr(place_distance, "m") else place_distance
            )

            result = base_result(place, media_url)
            result["distance"] = round(distance_m, 2) if distance_m else None

            result["categories"] = build_categories_data(place, request) or []
            build_sources(result, place, media_url)
            if wants_parties:
                result["parties"] = build_parties_data(place, request) or []
            results.append(
                project_fields(
                    result,
                    query,
                    "places",
                    {
                        "categories": "categories",
                        "sources": "sources",
                        "parties": "parties",
                    },
                )
            )

        return results  # type: ignore  # serialized dicts match schema shape at runtime


#: Optional members seeded in every detail result so selection
#: validity never depends on the row's data — absent data narrows to
#: "member missing", never a 400 (review finding #1).
_DETAIL_OPTIONAL_MEMBERS = ("amenity", "categories", "sources", "parties", "links")


def _narrow_place_detail(result: dict[str, Any], parsed: PlaceQuery) -> dict[str, Any]:
    """Apply ``fields[TYPE]`` selections to a place-detail result dict.

    Thin wrapper over :func:`server.apps.api.projection.project_fields`:
    validity, top-level required-keep and nested required-keep all come
    from the DTOs registered on ``PlaceDetailFields`` — including
    ``parties`` (review findings #1-#3: the former hand-rolled variant
    validated against runtime keys and dropped nested required
    fields). Members without data are seeded ``None`` so they stay
    valid selection names on every place, and stripped again after
    narrowing.
    """
    for member in _DETAIL_OPTIONAL_MEMBERS:
        result.setdefault(member, None)
    result = project_fields(
        result,
        parsed,
        "places",
        {
            "categories": "categories",
            "sources": "sources",
            "parties": "parties",
            "links": "links",
        },
    )
    for member in _DETAIL_OPTIONAL_MEMBERS:
        if result.get(member) is None:
            result.pop(member, None)
    return result


class PlaceController(ApiController):
    """Unified place detail — every GeoPlace, keyed by slug."""

    @modify(
        operation_id="get_place",
        headers=cache_headers(60),
    )
    def get(
        self,
        parsed_path: Path[PlacePath],
        parsed_query: Query[PlaceQuery],
    ) -> GeoPlaceDetailSchema:
        """Get a place.

        Unified detail for every place regardless of detail type (amenity, transport,
        admin, natural, none): base place fields plus optional members (categories,
        sources, amenity) under the `fields[places]` sparse-fieldset selection.
        Places are identified by slug; the numeric id is never exposed.
        """

        request = self.request
        query = parsed_query

        # Skip the DB cost when the field isn't in the selection —
        # same field_selected gating as search/nearby.
        wants_amenity = field_selected(query, "places", "amenity")
        wants_categories = field_selected(query, "places", "categories")
        wants_sources = field_selected(query, "places", "sources")
        wants_parties = field_selected(query, "places", "parties")
        wants_links = field_selected(query, "places", "links")

        queryset = GeoPlace.objects.filter(
            is_active=True,
            is_public=True,
            slug=parsed_path.slug,
        )
        if wants_amenity:
            # select_related: the block access below is then safe on
            # places without a detail row (cached None, no exception).
            queryset = queryset.select_related("amenity_detail")
        if wants_categories:
            queryset = prefetch_categories(queryset)
        if wants_sources:
            queryset = annotate_sources(queryset)
        if wants_parties:
            queryset = prefetch_parties(queryset)
        if wants_links:
            queryset = prefetch_links(queryset)

        place = queryset.first()
        if place is None:
            raise_not_found("Place not found")

        # Count the visit once we know the place exists (best-effort).
        from server.apps.visits.models import record_visit

        record_visit(request, place)

        from django.conf import settings as dj_settings
        from django.utils.translation import override

        media_url = dj_settings.MEDIA_URL
        if not media_url.startswith("http"):
            media_url = request.build_absolute_uri(media_url)

        # name/description/category/party strings are *_i18n reads —
        # activate the requested language for the whole build (the
        # spec promises `name` localized per lang; cache_page keys on
        # the full URL, so variants never mix).
        with override(query.lang):
            result = base_result(place, media_url)
            result["description"] = place.description_i18n  # noqa: WPS308
            result["detail_type"] = place.detail_type
            result["review_status"] = place.review_status

            # Always seed the block member so it stays a valid selection
            # name for every place type; absent blocks narrow to "member
            # missing", never a 400 (see _narrow_place_detail).
            result["amenity"] = (
                build_amenity_detail(place)
                if wants_amenity and place.detail_type == "amenity"
                else None
            )

            if wants_categories:
                categories_data = build_categories_data(place, request)
                if categories_data:
                    result["categories"] = categories_data

            if wants_sources:
                build_sources(result, place, media_url)

            if wants_parties:
                parties_data = build_parties_data(place, request)
                if parties_data:
                    result["parties"] = parties_data

            if wants_links:
                links_data = build_links_data(place, request)
                if links_data:
                    result["links"] = links_data

        return GeoPlaceDetailSchema(**_narrow_place_detail(result, query))


# Server-side page caching parity with the former ninja decorators
# (cache_page 300/60/60/60 + the per-endpoint Cache-Control headers).
# SEO/LLM surface (place meta + Markdown) and the generic static-map
# endpoint — appended after the core geo paths.
#
# Path grammar rule (place-detail-endpoint): fixed collection segments
# under places/ (search, nearby, overlays) are single lowercase words —
# the <geoplace:slug> converter grammar (at least one `-` or `_`)
# makes item and fixed paths structurally disjoint, so ordering of the
# entries below never affects resolution.
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
        "places/<geoplace:slug>",
        cache_page(60)(PlaceController.as_view()),
        name="get_place",
    ),
]

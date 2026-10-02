"""Image aggregation endpoints on dmr (mounted at /geo/images/)."""

import asyncio
import logging

import pydantic
from dmr import Path, Query, modify
from dmr.routing import path
from pydantic import Field

from django.contrib.gis.geos import Point
from django.contrib.gis.measure import D

from server.apps.api.controller import ApiController, cache_headers
from server.apps.translations import LanguageQuery, activate

from . import image_response_cache
from .models import GeoPlace
from .providers import (
    CamptocampProvider,
    MapillaryProvider,
    PanoramaxProvider,
    RefugesInfoProvider,
    WikimediaCommonsProvider,
    WodoreProvider,
    fetch_images_for_place,
    fetch_images_from_providers,
    post_process_images,
    provider_registry,
)
from .schemas import ImageCollectionResponse, ImageMetadataSchema

logger = logging.getLogger(__name__)


# Register providers on module load
provider_registry.register(WodoreProvider(place_type="geoplace"))
provider_registry.register(WodoreProvider(place_type="hut"))
provider_registry.register(WikimediaCommonsProvider())  # Replaces WikidataProvider
provider_registry.register(RefugesInfoProvider())  # Add refuges.info provider
provider_registry.register(MapillaryProvider())
provider_registry.register(PanoramaxProvider())
provider_registry.register(CamptocampProvider())


class NearbyImagesQuery(LanguageQuery):
    """Query parameters for the nearby-images endpoint."""

    lat: float = Field(
        description="Latitude in WGS84",
        ge=-90,
        le=90,
        json_schema_extra={"example": 46.570088},
    )
    lon: float = Field(
        description="Longitude in WGS84",
        ge=-180,
        le=180,
        json_schema_extra={"example": 8.2221},
    )
    radius: float = Field(
        50.0,
        description="Search radius in meters",
        gt=0,
        le=10000,
        json_schema_extra={"example": 5000.0},
    )
    sources: str | None = Field(
        None,
        description=("Comma-separated provider list (e.g., 'wodore,wikidata,flickr')"),
    )
    precision: str = Field(
        "precise",
        description="Coordinate precision: 'broad' (3), 'normal' (4), 'precise' (6)",
    )
    limit: int = Field(
        100,
        description="Maximum number of images to return",
        ge=1,
        le=500,
    )
    update_cache: bool = Field(
        False,
        description=(
            "Force cache refresh - bypass cache and update all cached "
            "data from providers"
        ),
    )


class _PlaceImagesQuery(LanguageQuery):
    """Shared query parameters of the place/hut image endpoints."""

    radius: float = Field(
        5000.0,
        description="Search radius in meters for external providers",
        gt=0,
        le=10000,
        json_schema_extra={"example": 5000.0},
    )
    sources: str | None = Field(
        None,
        description=(
            "Comma-separated provider list (e.g., 'wodore,wikidata,flickr'). "
            "If provided without wodore, wodore images are not shown but "
            "the place is still used for location."
        ),
    )
    limit: int = Field(
        100,
        description="Maximum number of images to return",
        ge=1,
        le=500,
    )
    update_cache: bool = Field(
        False,
        description=(
            "Force cache refresh - bypass cache and update all cached "
            "data from providers"
        ),
    )


class PlaceSlugPath(pydantic.BaseModel):
    """GeoPlace slug path parameter."""

    place_slug: str = Field(description="GeoPlace slug")


class HutSlugPath(pydantic.BaseModel):
    """Hut slug path parameter."""

    hut_slug: str = Field(description="Hut slug")


class NearbyImagesController(ApiController):
    """Images near a location from multiple sources (GeoJSON)."""

    @modify(
        operation_id="nearby_images",
        headers=cache_headers(300),  # 5 minutes cache
    )
    def get(self, parsed_query: Query[NearbyImagesQuery]) -> ImageCollectionResponse:
        """Get nearby images.

        GeoJSON FeatureCollection from multiple sources. Aggregates internal Wodore database images with external sources
        (Wikidata, Flickr, etc.). Returns GeoJSON Point features with full
        image metadata.

        Algorithm:
        1. Find GeoPlaces within 10m of the coordinate
        2. If found, use those places for provider queries
        3. If not found within 10m, expand radius incrementally
        4. Query all enabled providers in parallel
        5. Merge and deduplicate results
        6. Return GeoJSON FeatureCollection sorted by distance
        """
        query = parsed_query
        activate(query.lang)

        sources_list = None
        if query.sources:
            sources_list = [s.strip() for s in query.sources.split(",")]

        resp_key = image_response_cache.response_key(
            "nearby",
            image_response_cache.center_ident(query.lat, query.lon),
            radius=query.radius,
            sources=query.sources,
            lang=query.lang,
            limit=query.limit,
            precision=query.precision,
        )
        if not query.update_cache:
            cached, fresh = image_response_cache.get_response(resp_key)
            if cached is not None and fresh:
                return cached

        # Step 1: Find GeoPlaces and Huts within 10m radius
        query_point = Point(query.lon, query.lat, srid=4326)

        logger.debug(
            f"🔍 Searching for GeoPlaces and Huts near ({query.lat}, "
            f"{query.lon}) with radius {query.radius}m"
        )

        search_radius = 10  # meters
        max_radius = int(query.radius)

        geoplaces = []
        huts = []
        current_radius = search_radius

        while current_radius <= max_radius:
            geoplaces = list(
                GeoPlace.objects.filter(
                    is_active=True,
                    is_public=True,
                    location__distance_lte=(query_point, D(m=current_radius)),
                )
                .prefetch_related(
                    "source_associations__organization"
                )  # Prefetch sources for schema conversion
                .only("id", "slug", "name", "i18n", "location", "osm_tags")[:50]
            )

            from server.apps.huts.models import Hut

            huts = list(
                Hut.objects.filter(
                    is_active=True,
                    is_public=True,
                    location__distance_lte=(query_point, D(m=current_radius)),
                )
                .prefetch_related(
                    "hut_sources__organization"
                )  # Prefetch sources for schema conversion
                .only("id", "slug", "name", "i18n", "location")[:50]
            )

            if geoplaces or huts:
                break

            current_radius *= 2

        if not geoplaces and not huts:
            logger.warning(
                f"No GeoPlaces or Huts found within {max_radius}m, "
                "using coordinate only"
            )

        all_places = list(geoplaces) + list(huts)

        logger.debug(
            f"📸 Fetching images from "
            f"{len(provider_registry.get_all_providers())} providers..."
        )

        try:
            results = asyncio.run(
                fetch_images_from_providers(
                    geoplaces=all_places,  # Pass both GeoPlaces and Huts
                    lat=query.lat,
                    lon=query.lon,
                    radius=query.radius,
                    sources=sources_list,
                    precision=query.precision,
                    limit=query.limit,
                    update_cache=query.update_cache,
                )
            )
        except Exception as e:  # stale-cache fallback below
            logger.error(f"Error fetching images from providers: {e}")
            cached, _fresh = image_response_cache.get_response(resp_key)
            if cached is not None:
                logger.warning(
                    f"Stale fallback: serving cached response for nearby "
                    f"({query.lat},{query.lon})"
                )
                return cached
            results = []

        # Sort by score (primary), then by distance (secondary)
        results.sort(key=lambda r: (-r.score, r.distance_m))
        results = results[: query.limit]

        features = post_process_images(
            results, force_provider_refresh=query.update_cache
        )

        metadata = ImageMetadataSchema(
            total=len(features),
            sources_queried=sources_list
            or [p.source for p in provider_registry.get_all_providers()],
            query_radius_m=query.radius,
            center={"lat": query.lat, "lon": query.lon},
            geoplaces_found=len(geoplaces),
            huts_found=len(huts),
        )

        response = ImageCollectionResponse(
            type="FeatureCollection", features=features, metadata=metadata
        )
        image_response_cache.set_response(resp_key, response)
        return response


class PlaceImagesController(ApiController):
    """Images for a specific GeoPlace from multiple sources."""

    @modify(
        operation_id="images_for_place",
        headers=cache_headers(300),  # 5 minutes cache
    )
    def get(
        self,
        parsed_path: Path[PlaceSlugPath],
        parsed_query: Query[_PlaceImagesQuery],
    ) -> ImageCollectionResponse:
        """Get images for a place.

        From multiple sources; Wodore provider uses the place directly (very fast). External
        providers use the place's coordinates with the given radius.

        Returns GeoJSON Point features with full image metadata.
        """
        query = parsed_query
        place_slug = parsed_path.place_slug
        activate(query.lang)

        sources_list = None
        if query.sources:
            sources_list = [s.strip() for s in query.sources.split(",")]

        resp_key = image_response_cache.response_key(
            "place",
            place_slug,
            radius=query.radius,
            sources=query.sources,
            lang=query.lang,
            limit=query.limit,
        )
        if not query.update_cache:
            cached, fresh = image_response_cache.get_response(resp_key)
            if cached is not None and fresh:
                return cached

        from .pinning import maybe_enqueue_place_refresh, place_has_visible_pins

        place = GeoPlace.objects.filter(
            slug=place_slug, is_active=True, is_public=True
        ).first()

        # Pins fast path (openspec pin-external-images): the place already
        # has pinned/uploaded images — serve them from the DB via the
        # internal Wodore provider only; no external provider is contacted.
        serve_from_pins = bool(
            place
            and not sources_list
            and not query.update_cache
            and place_has_visible_pins(place)
        )

        if serve_from_pins and place is not None:
            # Queued refresh (never in-request): stale pins enqueue a q2
            # task; this visitor gets the current pins, the next one the
            # fresh set.
            maybe_enqueue_place_refresh(place)
            try:
                results = WodoreProvider(place_type="geoplace")._fetch_sync(
                    [], place.location.y, place.location.x, query.radius
                )
                place_info = {
                    "location": {"lat": place.location.y, "lon": place.location.x}
                }
            except Exception as e:
                logger.error(
                    f"Error fetching pinned images for place '{place_slug}': {e}"
                )
                cached, _fresh = image_response_cache.get_response(resp_key)
                if cached is not None:
                    logger.warning(
                        f"Stale fallback: serving cached response for place "
                        f"'{place_slug}'"
                    )
                    return cached
                raise
        else:
            try:
                results, place_info = asyncio.run(
                    fetch_images_for_place(
                        place_slug=place_slug,
                        place_type="geoplace",
                        radius=query.radius,
                        sources=sources_list,
                        limit=query.limit,
                        update_cache=query.update_cache,
                    )
                )
            except Exception as e:  # stale-cache fallback below
                logger.error(f"Error fetching images for place '{place_slug}': {e}")
                cached, _fresh = image_response_cache.get_response(resp_key)
                if cached is not None:
                    logger.warning(
                        f"Stale fallback: serving cached response for place "
                        f"'{place_slug}'"
                    )
                    return cached
                raise

            # Lazy pin-on-first-visit / forced re-pin (full default runs
            # only).
            if place is not None and not sources_list:
                try:
                    from .pinning import pin_place_images

                    stats = pin_place_images(place, results)
                    logger.info(f"Pinned images for place '{place_slug}': {stats}")
                    # Pinning bumped the response-cache version — recompute
                    # the key so this response is stored at the new version.
                    resp_key = image_response_cache.response_key(
                        "place",
                        place_slug,
                        radius=query.radius,
                        sources=query.sources,
                        lang=query.lang,
                        limit=query.limit,
                    )
                except Exception as e:
                    logger.error(f"Error pinning images for place '{place_slug}': {e}")

        results.sort(key=lambda r: (-r.score, r.distance_m))
        results = results[: query.limit]

        features = post_process_images(
            results, force_provider_refresh=query.update_cache
        )

        metadata = ImageMetadataSchema(
            total=len(features),
            sources_queried=sources_list
            or [p.source for p in provider_registry.get_all_providers()],
            query_radius_m=query.radius,
            center={
                "lat": place_info["location"]["lat"],
                "lon": place_info["location"]["lon"],
            },
            geoplaces_found=1,
            huts_found=0,
        )

        response = ImageCollectionResponse(
            type="FeatureCollection", features=features, metadata=metadata
        )
        image_response_cache.set_response(resp_key, response)
        return response


class HutImagesController(ApiController):
    """Images for a specific Hut from multiple sources."""

    @modify(
        operation_id="images_for_hut",
        headers=cache_headers(300),  # 5 minutes cache
    )
    def get(
        self,
        parsed_path: Path[HutSlugPath],
        parsed_query: Query[_PlaceImagesQuery],
    ) -> ImageCollectionResponse:
        """Get images for a hut.

        From multiple sources; Wodore provider uses the hut directly (very fast). External
        providers use the hut's coordinates with the given radius.

        Returns GeoJSON Point features with full image metadata.
        """
        query = parsed_query
        hut_slug = parsed_path.hut_slug
        activate(query.lang)

        sources_list = None
        if query.sources:
            sources_list = [s.strip() for s in query.sources.split(",")]

        resp_key = image_response_cache.response_key(
            "hut",
            hut_slug,
            radius=query.radius,
            sources=query.sources,
            lang=query.lang,
            limit=query.limit,
        )
        if not query.update_cache:
            cached, fresh = image_response_cache.get_response(resp_key)
            if cached is not None and fresh:
                return cached

        from server.apps.huts.models import Hut

        from .pinning import place_has_visible_pins

        hut = Hut.objects.filter(slug=hut_slug, is_active=True, is_public=True).first()

        serve_from_pins = bool(
            hut
            and not sources_list
            and not query.update_cache
            and place_has_visible_pins(hut)
        )

        if serve_from_pins and hut is not None:
            from .pinning import maybe_enqueue_place_refresh

            maybe_enqueue_place_refresh(hut)
            try:
                # Pure-DB fast path: the internal Wodore provider converts
                # the hut's associations (uploads + pins) to results — no
                # external provider, no async machinery needed.
                results = WodoreProvider(place_type="hut")._fetch_sync(
                    [], hut.location.y, hut.location.x, query.radius
                )
                place_info = {
                    "location": {"lat": hut.location.y, "lon": hut.location.x}
                }
            except Exception as e:
                logger.error(f"Error fetching pinned images for hut '{hut_slug}': {e}")
                cached, _fresh = image_response_cache.get_response(resp_key)
                if cached is not None:
                    logger.warning(
                        f"Stale fallback: serving cached response for hut '{hut_slug}'"
                    )
                    return cached
                raise
        else:
            try:
                results, place_info = asyncio.run(
                    fetch_images_for_place(
                        place_slug=hut_slug,
                        place_type="hut",
                        radius=query.radius,
                        sources=sources_list,
                        limit=query.limit,
                        update_cache=query.update_cache,
                    )
                )
            except Exception as e:
                logger.error(f"Error fetching images for hut '{hut_slug}': {e}")
                cached, _fresh = image_response_cache.get_response(resp_key)
                if cached is not None:
                    logger.warning(
                        f"Stale fallback: serving cached response for hut '{hut_slug}'"
                    )
                    return cached
                raise

            if hut is not None and not sources_list:
                try:
                    from .pinning import pin_place_images

                    stats = pin_place_images(hut, results)
                    logger.info(f"Pinned images for hut '{hut_slug}': {stats}")
                    resp_key = image_response_cache.response_key(
                        "hut",
                        hut_slug,
                        radius=query.radius,
                        sources=query.sources,
                        lang=query.lang,
                        limit=query.limit,
                    )
                except Exception as e:
                    logger.error(f"Error pinning images for hut '{hut_slug}': {e}")

        results.sort(key=lambda r: (-r.score, r.distance_m))
        results = results[: query.limit]

        features = post_process_images(
            results, force_provider_refresh=query.update_cache
        )

        metadata = ImageMetadataSchema(
            total=len(features),
            sources_queried=sources_list
            or [p.source for p in provider_registry.get_all_providers()],
            query_radius_m=query.radius,
            center={
                "lat": place_info["location"]["lat"],
                "lon": place_info["location"]["lon"],
            },
            geoplaces_found=0,
            huts_found=1,
        )

        response = ImageCollectionResponse(
            type="FeatureCollection", features=features, metadata=metadata
        )
        image_response_cache.set_response(resp_key, response)
        return response


paths = [
    path("nearby", NearbyImagesController.as_view(), name="nearby_images"),
    path(
        "place/<str:place_slug>",
        PlaceImagesController.as_view(),
        name="images_for_place",
    ),
    path(
        "hut/<str:hut_slug>",
        HutImagesController.as_view(),
        name="images_for_hut",
    ),
]

"""Image aggregation endpoints on dmr (mounted at /geo/images/)."""

import asyncio
import logging

import pydantic
from dmr import Path, Query, modify
from dmr.routing import path
from pydantic import Field

from django.conf import settings
from django.contrib.gis.geos import Point
from django.contrib.gis.measure import D
from django.http import HttpRequest

from server.apps.api.controller import ApiController, cache_headers, raise_not_found
from server.apps.api.ogmap import RENDER_VERSION
from server.apps.images.og import OG_MAP_EFFECT, OG_MAP_MARKER_SCALE, OG_MAP_ZOOM
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
from .schemas import (
    DEFAULT_THUMBHASHES,
    ImageCenterSchema,
    ImageCollectionResponse,
    ImageMetadataSchema,
)

logger = logging.getLogger(__name__)


# Register providers on module load
provider_registry.register(WodoreProvider(place_type="geoplace"))
provider_registry.register(WodoreProvider(place_type="hut"))
provider_registry.register(WikimediaCommonsProvider())  # Replaces WikidataProvider
provider_registry.register(RefugesInfoProvider())  # Add refuges.info provider
provider_registry.register(MapillaryProvider())
provider_registry.register(PanoramaxProvider())
provider_registry.register(CamptocampProvider())


class _CachedOnlyMixin(pydantic.BaseModel):
    """Shared ``cached_only`` parameter of the image endpoints.

    Fast call for in-process and preview callers (e.g. the hut meta
    og:image): serve whatever the response cache holds — fresh or stale
    — and never contact providers. The empty-collection miss keeps the
    contract simple; nothing is written back to the cache."""

    cached_only: bool = Field(
        False,
        description=(
            "Fast call: serve only a cached response (fresh or stale), "
            "never query providers — an empty collection when nothing "
            "is cached. Mutually exclusive with update_cache."
        ),
    )

    @pydantic.model_validator(mode="after")
    def _cached_only_excludes_update_cache(self):
        if self.cached_only and getattr(self, "update_cache", False):
            raise ValueError("cached_only and update_cache are mutually exclusive")
        return self


class NearbyImagesQuery(_CachedOnlyMixin, LanguageQuery):
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


class _PlaceImagesQuery(_CachedOnlyMixin, LanguageQuery):
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
    static_map_fallback: bool = Field(
        True,
        description=(
            "When the entity has no images, include the generated "
            "static-map card (zoom 15, spotlight effect, type-symbol "
            "marker) as a single feature (is_fallback=true). Opt out "
            "with false to receive a plain empty collection."
        ),
    )


class PlaceSlugPath(pydantic.BaseModel):
    """GeoPlace slug path parameter."""

    place_slug: str = Field(description="GeoPlace slug")


class HutSlugPath(pydantic.BaseModel):
    """Hut slug path parameter."""

    hut_slug: str = Field(description="Hut slug")


def _empty_images_response(
    *,
    lat: float,
    lon: float,
    radius: float,
    sources_list: list[str] | None,
    features: list | None = None,
) -> ImageCollectionResponse:
    """(Near-)empty FeatureCollection for ``cached_only`` misses:
    nothing was cached, so the answer is whatever the caller's
    ``static_map_fallback`` adds — without contacting any provider.
    Never written back to the cache."""
    features = features or []
    return ImageCollectionResponse(
        type="FeatureCollection",
        features=features,
        metadata=ImageMetadataSchema(
            total=len(features),
            sources_queried=sources_list or [],
            query_radius_m=radius,
            center=ImageCenterSchema(lat=lat, lon=lon),
            geoplaces_found=0,
            huts_found=0,
        ),
    )


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
        cached = None
        if not query.update_cache:
            cached, fresh = image_response_cache.get_response(resp_key)
            if cached is not None and fresh:
                return cached
        if query.cached_only:
            # Fast call: the cached response if any (stale included), else
            # an empty collection — providers are never contacted and
            # nothing is written back.
            if cached is not None:
                return cached
            return _empty_images_response(
                lat=query.lat,
                lon=query.lon,
                radius=query.radius,
                sources_list=sources_list,
            )

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


def _map_fallback_feature(
    request: HttpRequest,
    *,
    slug: str,
    lat: float,
    lon: float,
    modified,
    place_type: str,
) -> dict:
    """Static-map fallback feature for entities without any images.

    Generated exactly like the og preview cards (server.apps.images.og):
    zoom 15, spotlight effect, scaled type-symbol marker — in the
    gallery's size variants."""
    from urllib.parse import urlencode

    def map_url(size: str) -> str:
        query = urlencode(
            {
                "place": slug,
                "place_type": place_type,
                "size": size,
                "zoom": OG_MAP_ZOOM,
                "effect": OG_MAP_EFFECT,
                "marker_scale": OG_MAP_MARKER_SCALE,
                # No baked attribution strip: the OpenTopoMap/OSM credits
                # travel in the feature's license/author/attribution
                # metadata instead (the gallery renders them like for
                # provider photos).
                "attribution": "false",
                # v busts BOTH caches: the raw render storage and the
                # imagor composites built on this URL (renderer changes
                # propagate via RENDER_VERSION).
                "v": f"{modified:%Y%m%dT%H%M%S}r{RENDER_VERSION}",
            }
        )
        return request.build_absolute_uri(f"/v1/geo/map/static?{query}")

    # Same variant pipeline as the provider photos: one map render per
    # aspect group as the source, then signed imagor downscale variants
    # (xs–xl, quality 85) with the identical size presets — the
    # gallery treats the fallback exactly like any other image and
    # imagor caches/transforms it like one.
    from server.apps.geometries.providers.base import (
        _calculate_constrained_size,
    )
    from server.apps.images.transfomer import ImagorImage

    quality = 85
    aspect_sources = {
        # aspect group: (source render size, variant presets)
        "square": (
            (1000, 1000),
            {
                "xs": (200, 200),
                "sm": (400, 400),
                "md": (1200, 1200),
                "lg": (2000, 2000),
                "xl": (4000, 4000),
            },
        ),
        "landscape": (
            (1200, 630),
            {
                "xs": (200, 133),
                "sm": (400, 267),
                "md": (1200, 800),
                "lg": (2000, 1333),
                "xl": (4000, 2666),
            },
        ),
        "portrait": (
            (1000, 1500),
            {
                "xs": (133, 200),
                "sm": (267, 400),
                "md": (900, 1350),
                "lg": (1500, 2250),
                "xl": (3000, 4500),
            },
        ),
    }
    urls: dict = {}
    sizes: dict = {"raw": {"width": 1200, "height": 630}}
    for group, ((sw, sh), presets) in aspect_sources.items():
        source = ImagorImage(map_url(f"{sw}x{sh}"))
        variants = {}
        for key, (tw, th) in presets.items():
            cw, ch = _calculate_constrained_size(tw, th, sw, sh)
            variants[key] = source.transform(
                size=f"{cw}x{ch}", quality=quality
            ).get_full_url()
            if group == "landscape":
                # The feature's own orientation is landscape — report
                # its constrained dims (mirrors _build_sizes).
                sizes[key] = {"width": cw, "height": ch}
        urls[group] = variants
    landscape_raw = map_url("1200x630")
    urls["original"] = {
        # raw stays the direct endpoint URL: the og compose wraps it in
        # imagor itself (og_map_card_url).
        "raw": landscape_raw,
        "proxy": ImagorImage(landscape_raw).transform().get_full_url(),
    }
    # License/attribution metadata mirrors the provider photos (same
    # shape, HTML links) — the gallery renders it exactly like any
    # other image's credits. Map data: OpenTopoMap tiles are CC-BY-SA
    # derivatives of OpenStreetMap data (with SRTM elevation).
    license_url = "https://creativecommons.org/licenses/by-sa/4.0/"
    attribution_full = (
        "© OpenTopoMap (CC-BY-SA) · © SRTM · © OpenStreetMap contributors"
    )
    license_short = f'<a href="{license_url}" target="_blank">CC-BY-SA-4.0</a>'
    attribution_author = (
        "© OpenTopoMap / "
        '<a href="https://www.openstreetmap.org/copyright" '
        'target="_blank" rel="nofollow">OpenStreetMap contributors</a>'
    )
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {
            "provider": {
                "slug": "wodore-map",
                "name": "Static map",
                "url": settings.FRONTEND_DOMAIN,
                "icon": None,
                "description": "Generated OpenTopoMap card (no photo available)",
            },
            "source_id": f"static-map:{slug}",
            "source_url": None,
            "image_type": "flat",
            "captured_at": None,
            "distance_m": 0.0,
            "attribution": {
                "short": f"{license_short} · {attribution_author}",
                "full": attribution_full,
                "license_icon": None,
                "license_short": license_short,
                "license_full": "CC BY-SA 4.0",
                "author": attribution_author,
            },
            "author": {
                "name": "OpenTopoMap / OpenStreetMap contributors",
                "url": None,
            },
            "license": {
                "slug": "cc-by-sa-4-0",
                "name": "CC BY-SA 4.0 (map data)",
                "url": license_url,
                "icon": None,
            },
            "urls": urls,
            "sizes": sizes,
            "is_portrait": False,
            "place": None,
            "score": 0,
            "is_fallback": True,
            "thumbhashes": DEFAULT_THUMBHASHES.model_dump(),
        },
    }


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
        request = self.request
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
            fallback=query.static_map_fallback,
        )
        cached = None
        if not query.update_cache:
            cached, fresh = image_response_cache.get_response(resp_key)
            if cached is not None and fresh:
                return cached
        if query.cached_only:
            # Fast call: the cached response if any (stale included), else
            # the empty collection with at most the static-map fallback —
            # providers are never contacted and nothing is written back.
            place = GeoPlace.objects.filter(
                slug=place_slug, is_active=True, is_public=True
            ).first()
            if place is None:
                raise_not_found(f"GeoPlace '{place_slug}' not found")
            return cached_only_response(
                cached=cached,
                entity=place,
                request=request,
                place_type="geoplace",
                radius=query.radius,
                sources_list=sources_list,
                static_map_fallback=query.static_map_fallback,
            )

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
                        fallback=query.static_map_fallback,
                    )
                except Exception as e:
                    logger.error(f"Error pinning images for place '{place_slug}': {e}")

        results.sort(key=lambda r: (-r.score, r.distance_m))
        results = results[: query.limit]

        features = post_process_images(
            results, force_provider_refresh=query.update_cache
        )

        if (
            query.static_map_fallback
            and not features
            and place is not None
            and place.location
        ):
            features = [
                _map_fallback_feature(
                    request,
                    slug=place.slug,
                    lat=place.location.y,
                    lon=place.location.x,
                    modified=place.modified,
                    place_type="geoplace",
                )
            ]

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
        request = self.request
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
            fallback=query.static_map_fallback,
        )
        cached = None
        if not query.update_cache:
            cached, fresh = image_response_cache.get_response(resp_key)
            if cached is not None and fresh:
                return cached
        from server.apps.huts.models import Hut

        if query.cached_only:
            # Fast call: the cached response if any (stale included), else
            # the empty collection with at most the static-map fallback —
            # providers are never contacted and nothing is written back.
            hut = Hut.objects.filter(
                slug=hut_slug, is_active=True, is_public=True
            ).first()
            if hut is None:
                raise_not_found(f"Hut '{hut_slug}' not found")
            return cached_only_response(
                cached=cached,
                entity=hut,
                request=request,
                place_type="hut",
                radius=query.radius,
                sources_list=sources_list,
                static_map_fallback=query.static_map_fallback,
            )

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
                        fallback=query.static_map_fallback,
                    )
                except Exception as e:
                    logger.error(f"Error pinning images for hut '{hut_slug}': {e}")

        results.sort(key=lambda r: (-r.score, r.distance_m))
        results = results[: query.limit]

        features = post_process_images(
            results, force_provider_refresh=query.update_cache
        )

        if (
            query.static_map_fallback
            and not features
            and hut is not None
            and hut.location
        ):
            features = [
                _map_fallback_feature(
                    request,
                    slug=hut.slug,
                    lat=hut.location.y,
                    lon=hut.location.x,
                    modified=hut.modified,
                    place_type="hut",
                )
            ]

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


#: The hut/place page gallery's request shape (frontend ``useHutImages``/
#: ``useMediaImages``: radius 50 m, 20 images, all sources) plus the
#: endpoints' default static-map fallback. The og:image lookups must
#: read exactly the cache entries these parameters produce — the same
#: images the pages render (fallback features are skipped there).
GALLERY_QUERY_SHAPE = {"radius": 50.0, "sources": None, "limit": 20, "fallback": True}


def cached_only_response(
    *,
    cached: ImageCollectionResponse | None,
    entity,
    request: HttpRequest,
    place_type: str,
    radius: float,
    sources_list: list[str] | None,
    static_map_fallback: bool,
) -> ImageCollectionResponse:
    """The ``cached_only=true`` answer for one entity (Hut or
    GeoPlace): the cached response if any (stale included), else the
    empty collection with at most the static-map fallback feature.

    Providers are never contacted and nothing is written back. Shared
    by the controllers' cached_only branches and the in-process og
    helpers (``hut_gallery_response``/``place_gallery_response``).
    ``entity`` is duck-typed: slug, location, modified."""
    if cached is not None:
        return cached
    location = entity.location
    features = []
    if static_map_fallback and location is not None:
        features = [
            _map_fallback_feature(
                request,
                slug=entity.slug,
                lat=location.y,
                lon=location.x,
                modified=entity.modified,
                place_type=place_type,
            )
        ]
    return _empty_images_response(
        lat=location.y if location is not None else 0.0,
        lon=location.x if location is not None else 0.0,
        radius=radius,
        sources_list=sources_list,
        features=features,
    )


def hut_gallery_response(
    hut, request: HttpRequest, *, lang: str | None
) -> ImageCollectionResponse:
    """The image service's answer for the hut page's gallery, default
    parameters, for in-process callers (the hut meta og:image).

    Identical to ``GET /v1/geo/images/hut/{slug}?cached_only=true``:
    the cached gallery response if any (stale included; imagery is
    language-independent — the requested language's entry first, then
    any other), else the static-map fallback feature."""
    cached = None
    for candidate_lang in dict.fromkeys((lang, "en", "de", "fr", "it")):
        if candidate_lang is None:
            continue
        entry = cached_hut_images(hut.slug, lang=candidate_lang)
        if entry is not None and entry.features:
            cached = entry
            break
    return cached_only_response(
        cached=cached,
        entity=hut,
        request=request,
        place_type="hut",
        radius=GALLERY_QUERY_SHAPE["radius"],
        sources_list=None,
        static_map_fallback=GALLERY_QUERY_SHAPE["fallback"],
    )


def place_gallery_response(
    place, request: HttpRequest, *, lang: str | None = None
) -> ImageCollectionResponse:
    """The image service's answer for the place page's gallery (the
    place SEO surface's og:image) — see :func:`hut_gallery_response`.
    The place meta endpoint has no lang parameter, so any cached
    language's entry counts."""
    cached = None
    for candidate_lang in ("en", "de", "fr", "it"):
        entry = cached_place_images(place.slug, lang=candidate_lang)
        if entry is not None and entry.features:
            cached = entry
            break
    return cached_only_response(
        cached=cached,
        entity=place,
        request=request,
        place_type="geoplace",
        radius=GALLERY_QUERY_SHAPE["radius"],
        sources_list=None,
        static_map_fallback=GALLERY_QUERY_SHAPE["fallback"],
    )


def cached_hut_images(hut_slug: str, *, lang: str) -> ImageCollectionResponse | None:
    """Cache-only answer of the images-by-hut endpoint for in-process
    callers (the hut meta endpoint's og:image).

    Returns exactly the response cached for the gallery's request shape
    — fresh or stale — or ``None`` when nothing is cached. Equivalent to
    ``GET /v1/geo/images/hut/{slug}?cached_only=true``: providers are
    never contacted, nothing is pinned or written back."""
    key = image_response_cache.response_key(
        "hut", hut_slug, lang=lang, **GALLERY_QUERY_SHAPE
    )
    cached, _fresh = image_response_cache.get_response(key)
    return cached


def cached_place_images(
    place_slug: str, *, lang: str
) -> ImageCollectionResponse | None:
    """Cache-only answer of the images-for-place endpoint for the place
    SEO surface's og:image — see :func:`cached_hut_images`."""
    key = image_response_cache.response_key(
        "place", place_slug, lang=lang, **GALLERY_QUERY_SHAPE
    )
    cached, _fresh = image_response_cache.get_response(key)
    return cached


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

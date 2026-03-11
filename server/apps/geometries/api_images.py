"""
API endpoints for Image aggregation.
Separate router to allow mounting at /geo/images/
"""

import logging

from django.contrib.gis.geos import Point
from ninja import Query, Router
from ninja.decorators import decorate_view

from django.contrib.gis.measure import D
from django.http import HttpRequest, HttpResponse
from django.views.decorators.cache import cache_control

from server.apps.translations import LanguageParam, activate, with_language_param

from .models import GeoPlace
from .schemas import (
    ImageCollectionResponse,
    ImageMetadataSchema,
)
from .providers import (
    fetch_images_from_providers,
    provider_registry,
    deduplicate_images,
    post_process_images,
    WodoreProvider,
    WikimediaCommonsProvider,
    MapillaryProvider,
    PanoramaxProvider,
    CamptocampProvider,
)

router = Router(tags=["geoimages"])
logger = logging.getLogger(__name__)


# Register providers on module load
provider_registry.register(WodoreProvider(place_type="geoplace"))
provider_registry.register(WodoreProvider(place_type="hut"))
provider_registry.register(WikimediaCommonsProvider())  # Replaces WikidataProvider
# provider_registry.register(FlickrProvider())
provider_registry.register(MapillaryProvider())
provider_registry.register(PanoramaxProvider())
provider_registry.register(CamptocampProvider())


@router.get(
    "nearby",
    response=ImageCollectionResponse,
    exclude_unset=True,
    operation_id="nearby_images",
)
@decorate_view(cache_control(max_age=300))  # 5 minutes cache
@with_language_param("lang")
def nearby_images(
    request: HttpRequest,
    response: HttpResponse,
    lang: LanguageParam,
    lat: float = Query(
        ..., description="Latitude in WGS84", ge=-90, le=90, example="46.570088"
    ),
    lon: float = Query(
        ..., description="Longitude in WGS84", ge=-180, le=180, example="8.2221"
    ),
    radius: float = Query(
        50.0, description="Search radius in meters", gt=0, le=10000, example="5000.0"
    ),
    sources: str | None = Query(
        None,
        description="Comma-separated provider list (e.g., 'wodore,wikidata,flickr')",
    ),
    precision: str = Query(
        "precise",
        description="Coordinate precision: 'broad' (3), 'normal' (4), 'precise' (6)",
    ),
    limit: int = Query(
        100,
        description="Maximum number of images to return",
        ge=1,
        le=500,
    ),
) -> ImageCollectionResponse:
    """
    Get images near a location from multiple sources as a GeoJSON FeatureCollection.

    Aggregates internal Wodore database images with external sources (Wikidata, Flickr, etc.).
    Returns GeoJSON Point features with full image metadata.

    Algorithm:
    1. Find GeoPlaces within 10m of the coordinate
    2. If found, use those places for provider queries
    3. If not found within 10m, expand radius incrementally
    4. Query all enabled providers in parallel
    5. Merge and deduplicate results
    6. Return GeoJSON FeatureCollection sorted by distance

    Providers are queried with GeoPlace objects, so they can extract
    required information (e.g., QID from osm_tags for Wikidata).
    """
    import asyncio

    activate(lang)

    # Parse sources parameter
    sources_list = None
    if sources:
        sources_list = [s.strip() for s in sources.split(",")]

    # Step 1: Find GeoPlaces and Huts within 10m radius
    query_point = Point(lon, lat, srid=4326)

    logger.debug(
        f"🔍 Searching for GeoPlaces and Huts near ({lat}, {lon}) with radius {radius}m"
    )
    logger.debug(f"Precision level: {precision}")
    logger.debug(f"Requested sources: {sources_list}")

    # Start with 10m radius as specified
    search_radius = 10  # meters
    max_radius = int(radius)  # Already in meters

    geoplaces = []
    huts = []
    current_radius = search_radius

    while current_radius <= max_radius:
        # Search for GeoPlaces
        geoplaces = list(
            GeoPlace.objects.filter(
                is_active=True,
                is_public=True,
                location__distance_lte=(query_point, D(m=current_radius)),
            ).only("id", "slug", "name", "i18n", "location", "osm_tags")[:50]
        )

        # Search for Huts
        from server.apps.huts.models import Hut

        huts = list(
            Hut.objects.filter(
                is_active=True,
                is_public=True,
                location__distance_lte=(query_point, D(m=current_radius)),
            ).only("id", "slug", "name", "i18n", "location")[:50]
        )

        logger.debug(
            f"Search radius {current_radius}m: Found {len(geoplaces)} GeoPlaces, {len(huts)} Huts"
        )

        if geoplaces or huts:
            for place in geoplaces:
                qid = place.osm_tags.get("wikidata") if place.osm_tags else None
                logger.debug(f"  - GeoPlace: {place.slug} (QID: {qid})")
            for hut in huts:
                logger.debug(f"  - Hut: {hut.slug}")

            logger.info(
                f"Found {len(geoplaces)} GeoPlaces and {len(huts)} Huts within {current_radius}m"
            )
            break

        # Double the search radius if no places found
        current_radius *= 2

    if not geoplaces and not huts:
        logger.warning(
            f"No GeoPlaces or Huts found within {max_radius}m, using coordinate only"
        )

    # Combine both lists
    all_places = list(geoplaces) + list(huts)

    # Step 2: Fetch images from all providers
    logger.debug(
        f"📸 Fetching images from {len(provider_registry.get_all_providers())} providers..."
    )

    try:
        # Run async function in sync context
        results = asyncio.run(
            fetch_images_from_providers(
                geoplaces=all_places,  # Pass both GeoPlaces and Huts
                lat=lat,
                lon=lon,
                radius=radius,
                sources=sources_list,
                precision=precision,
                limit=limit,  # Pass limit to providers
            )
        )
        logger.debug(f"📊 Total raw results from all providers: {len(results)} images")
    except Exception as e:
        logger.error(f"Error fetching images from providers: {e}")
        results = []

    # Step 3: Deduplicate results
    logger.debug(f"🔄 Deduplicating {len(results)} images...")
    results = deduplicate_images(results)
    logger.debug(f"✓ After deduplication: {len(results)} unique images")

    # Step 4: Sort by score (primary), then by distance (secondary)
    results.sort(key=lambda r: (-r.score, r.distance_m))

    # Step 5: Limit results
    logger.debug(f"✂️  Limiting to {limit} results (had {len(results)})")
    results = results[:limit]

    # Step 6: Post-process results (generate URLs, convert to GeoJSON)
    logger.debug(f"🎨 Post-processing {len(results)} results...")
    features = post_process_images(results)

    # Construct metadata
    metadata = ImageMetadataSchema(
        total=len(features),
        sources_queried=sources_list
        or [p.source for p in provider_registry.get_all_providers()],
        query_radius_m=radius,
        center={"lat": lat, "lon": lon},
        geoplaces_found=len(geoplaces),
        huts_found=len(huts),
    )

    return ImageCollectionResponse(
        type="FeatureCollection", features=features, metadata=metadata
    )

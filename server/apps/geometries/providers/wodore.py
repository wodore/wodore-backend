"""
Provider for Wodore internal database images.
Works with both GeoPlaces and Huts.
"""

import logging
from typing import Any

from asgiref.sync import sync_to_async

from django.contrib.gis.geos import Point
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.measure import D

from .base import ImageProvider, ImageResult, ImageArea

logger = logging.getLogger(__name__)


class WodoreProvider(ImageProvider):
    """
    Provider for internal Wodore database images.
    Replaces the old 'own' provider.
    """

    source = "wodore"
    cache_ttl = 0  # No caching - always live
    priority = 1  # Highest priority

    def __init__(self, place_type: str = "geoplace"):
        """
        Initialize WodoreProvider.

        Args:
            place_type: Type of place ('geoplace' or 'hut')
        """
        self.place_type = place_type
        logger.info(f"Initialized WodoreProvider for {place_type}")

    async def fetch(
        self,
        geoplaces: list[Any],
        lat: float,
        lon: float,
        radius: float,
        limit: int = 100,
    ) -> list[ImageResult]:
        """
        Fetch images from internal Wodore database.

        Args:
            geoplaces: List of GeoPlace objects within radius
            lat: Query latitude
            lon: Query longitude
            radius: Search radius in meters

            limit: Maximum number of results to return

        Returns:
            List of ImageResult objects
        """
        try:
            logger.debug(f"🏔️  WodoreProvider: Fetching with {len(geoplaces)} geoplaces")

            # Wrap the synchronous fetch in sync_to_async
            return await sync_to_async(self._fetch_sync)(geoplaces, lat, lon, radius)
        except Exception as e:
            logger.error(f"WodoreProvider ({self.place_type}) error: {e}")
            return []

    def _fetch_sync(
        self,
        geoplaces: list[Any],
        lat: float,
        lon: float,
        radius: float,
    ) -> list[ImageResult]:
        """
        Synchronous implementation of fetch.
        Called by sync_to_async in the async fetch method.
        """

        query_point = Point(lon, lat, srid=4326)

        # Import based on place type
        if self.place_type == "geoplace":
            from server.apps.geometries.models import GeoPlace

            # Get GeoPlaces within 10m radius
            places = (
                GeoPlace.objects.filter(
                    is_active=True,
                    is_public=True,
                    location__distance_lte=(query_point, D(m=10)),
                )
                .annotate(distance=Distance("location", query_point))
                .prefetch_related("image_associations__image__license")
            )

            results = []
            for place in places:
                place_qid = None
                if hasattr(place, "osm_tags") and place.osm_tags:
                    place_qid = place.osm_tags.get("wikidata")

                logger.info(
                    f"WodoreProvider: Processing place '{place.slug}' (QID: {place_qid})"
                )

                # Get images through association model
                for assoc in place.image_associations.all():
                    img = assoc.image
                    # Filter: must be active, approved, and not marked for no publication
                    if not img.is_active:
                        continue
                    if img.review_status != "approved":
                        continue
                    if img.license.no_publication:
                        continue

                    distance_m = (
                        place.distance.m
                        if hasattr(place.distance, "m")
                        else place.distance
                    )

                    # Generate attribution using base helper
                    from .base import _build_attribution, _get_license_info

                    # Get license info from database
                    license_info = _get_license_info(img.license.slug)

                    # Get provider info from source_org
                    provider_slug = "wodore"  # Default fallback
                    provider_name = "wodore"
                    provider_url = None
                    provider_icon = None
                    if img.source_org:
                        provider_slug = (
                            img.source_org.slug
                        )  # Use slug for provider field
                        provider_name = (
                            img.source_org.name_i18n or img.source_org.slug
                        )  # Use name for attribution
                        provider_url = img.source_org.url
                        # Generate provider icon URL if logo exists
                        if img.source_org.logo:
                            from server.apps.images.transfomer import ImagorImage

                            imagor_img = ImagorImage(img.source_org.logo)
                            provider_icon = imagor_img.transform(
                                size="128x128", quality=85
                            ).get_full_url()

                    attribution_data = _build_attribution(
                        author=img.author,
                        author_url=img.author_url,
                        license_slug=img.license.slug,
                        license_name=license_info["name"],
                        license_url=license_info["url"],
                        provider_name=provider_name,
                        provider_url=provider_url,
                        source_url=img.source_url,
                        provider_icon=provider_icon,
                        license_icons=license_info.get("icons"),
                    )
                    attribution = attribution_data["short"]

                    # Extract dimensions from image_meta
                    width = None
                    height = None
                    if img.image_meta:
                        width = img.image_meta.get("width")
                        height = img.image_meta.get("height")

                    # Extract focal and crop areas
                    focal_area = self._extract_focal_area(img)
                    crop_area = self._extract_crop_area(img)

                    result = ImageResult(
                        provider=provider_slug,  # Use source_org slug (e.g., "sac", "wikimedia")
                        source_id=str(img.id),
                        source_url=img.source_url,
                        image_type="flat",  # Default for wodore images
                        captured_at=img.capture_date,
                        location=place.location,
                        distance_m=distance_m,
                        license_slug=img.license.slug,
                        attribution=attribution,
                        author=img.author,
                        url_large=img.source_url_raw or str(img.image),
                        url_medium=None,
                        place={
                            "id": place.id,
                            "slug": place.slug,
                            "name": place.name_i18n,
                            "location": {
                                "lat": place.location.y,
                                "lon": place.location.x,
                            },
                        }
                        if place
                        else None,
                        score=90,  # Wodore images are highest quality (internal, curated)
                        width=width,
                        height=height,
                        focal=focal_area,
                        crop=crop_area,
                    )
                    results.append(result)

            logger.info(
                f"WodoreProvider ({self.place_type}): Found {len(results)} images from {len(places)} places"
            )
            return results

        elif self.place_type == "hut":
            from server.apps.huts.models import Hut

            # Get Huts within 10m radius
            huts = (
                Hut.objects.filter(
                    is_active=True,
                    is_public=True,
                    location__distance_lte=(query_point, D(m=10)),
                )
                .annotate(distance=Distance("location", query_point))
                .prefetch_related("image_set__license")
            )

            results = []
            for hut in huts:
                # Try to get QID from OSM source
                hut_qid = None

                # Debug: Log all sources
                logger.debug(f"Hut '{hut.slug}' has {hut.hut_sources.count()} sources:")
                for source in hut.hut_sources.all():
                    logger.debug(f"  - Source: {source.organization.slug}")
                    if source.source_data:
                        keys = (
                            list(source.source_data.keys())
                            if isinstance(source.source_data, dict)
                            else type(source.source_data)
                        )
                        logger.debug(f"    source_data keys: {keys}")
                        # Log if tags exist
                        if (
                            isinstance(source.source_data, dict)
                            and "tags" in source.source_data
                        ):
                            tags = source.source_data["tags"]
                            if isinstance(tags, dict):
                                qid = tags.get("wikidata")
                                if qid:
                                    logger.info(
                                        f"    ✓ WIKIDATA QID in {source.organization.slug}: {qid}"
                                    )

                try:
                    # Try both "osm" and "openstreetmap" as organization slugs
                    osm_source = hut.hut_sources.filter(
                        organization__slug__in=["osm", "openstreetmap"]
                    ).first()
                    if (
                        osm_source
                        and osm_source.source_data
                        and isinstance(osm_source.source_data, dict)
                    ):
                        # OSM tags are in source_data
                        tags = osm_source.source_data.get("tags")
                        if tags and isinstance(tags, dict):
                            hut_qid = tags.get("wikidata")
                            if hut_qid:
                                logger.info(
                                    f"✓ Extracted QID {hut_qid} from OSM source for '{hut.slug}'"
                                )
                except Exception as e:
                    logger.debug(
                        f"Could not extract QID from OSM source for {hut.slug}: {e}"
                    )

                logger.info(
                    f"WodoreProvider: Processing hut '{hut.slug}' (QID: {hut_qid})"
                )

                # Get images through reverse relation
                for img in hut.image_set.all():
                    logger.debug(
                        f"  - Image {img.id}: is_active={img.is_active}, review_status={img.review_status}, license.no_publication={img.license.no_publication if img.license else 'No license'}"
                    )

                    # Filter: must be active, approved, and not marked for no publication
                    if not img.is_active:
                        logger.debug("    ✗ Skipped (not active)")
                        continue
                    if img.review_status != "approved":
                        logger.debug(
                            f"    ✗ Skipped (review_status={img.review_status})"
                        )
                        continue
                    if img.license.no_publication:
                        logger.debug(
                            f"    ✗ Skipped (license marked for no publication: {img.license.slug})"
                        )
                        continue

                    logger.debug(
                        f"    ✓ Included: {img.caption_i18n[:50] if img.caption_i18n else 'No caption'}"
                    )
                    distance_m = (
                        hut.distance.m if hasattr(hut.distance, "m") else hut.distance
                    )

                    # Generate attribution using base helper
                    from .base import _build_attribution, _get_license_info

                    # Get license info from database
                    license_info = _get_license_info(img.license.slug)

                    # Get provider info from source_org
                    provider_slug = "wodore"  # Default fallback
                    provider_name = "wodore"
                    provider_url = None
                    provider_icon = None
                    if img.source_org:
                        provider_slug = (
                            img.source_org.slug
                        )  # Use slug for provider field
                        provider_name = (
                            img.source_org.name_i18n or img.source_org.slug
                        )  # Use name for attribution
                        provider_url = img.source_org.url
                        # Generate provider icon URL if logo exists
                        if img.source_org.logo:
                            from server.apps.images.transfomer import ImagorImage

                            imagor_img = ImagorImage(img.source_org.logo)
                            provider_icon = imagor_img.transform(
                                size="128x128", quality=85
                            ).get_full_url()

                    attribution_data = _build_attribution(
                        author=img.author,
                        author_url=img.author_url,
                        license_slug=img.license.slug,
                        license_name=license_info["name"],
                        license_url=license_info["url"],
                        provider_name=provider_name,
                        provider_url=provider_url,
                        source_url=img.source_url,
                        provider_icon=provider_icon,
                        license_icons=license_info.get("icons"),
                    )
                    attribution = attribution_data["short"]

                    # Extract dimensions from image_meta
                    width = None
                    height = None
                    if img.image_meta:
                        width = img.image_meta.get("width")
                        height = img.image_meta.get("height")

                    # Extract focal and crop areas
                    focal_area = self._extract_focal_area(img)
                    crop_area = self._extract_crop_area(img)

                    result = ImageResult(
                        provider=provider_slug,  # Use source_org slug (e.g., "sac", "wikimedia")
                        source_id=str(img.id),
                        source_url=img.source_url,
                        image_type="flat",  # Default for wodore images
                        captured_at=img.capture_date,
                        location=hut.location,
                        distance_m=distance_m,
                        license_slug=img.license.slug,
                        attribution=attribution,
                        author=img.author,
                        url_large=img.source_url_raw or str(img.image),
                        url_medium=None,
                        place={
                            "id": hut.id,
                            "slug": hut.slug,
                            "name": hut.name_i18n,
                            "location": {
                                "lat": hut.location.y,
                                "lon": hut.location.x,
                            },
                        }
                        if hut
                        else None,
                        score=90,  # Wodore images are highest quality (internal, curated)
                        width=width,
                        height=height,
                        focal=focal_area,
                        crop=crop_area,
                    )
                    results.append(result)

            logger.info(
                f"WodoreProvider ({self.place_type}): Found {len(results)} images from {len(huts)} huts"
            )
            return results

    def _extract_focal_area(self, image: Any) -> ImageArea | None:
        """
        Extract focal area from image_meta.

        Args:
            image: Image model instance

        Returns:
            ImageArea if focal data exists, None otherwise
        """
        if not image.image_meta:
            return None

        focal = image.image_meta.get("focal")
        if not focal:
            return None

        try:
            return ImageArea(
                x1=float(focal.get("x1", 0)),
                y1=float(focal.get("y1", 0)),
                x2=float(focal.get("x2", 1)),
                y2=float(focal.get("y2", 1)),
            )
        except (ValueError, TypeError) as e:
            logger.warning(f"Invalid focal data for image {image.id}: {e}")
            return None

    def _extract_crop_area(self, image: Any) -> ImageArea | None:
        """
        Extract crop area from image_meta.

        Args:
            image: Image model instance

        Returns:
            ImageArea if crop data exists, None otherwise
        """
        if not image.image_meta:
            return None

        crop = image.image_meta.get("crop")
        if not crop:
            return None

        try:
            return ImageArea(
                x1=float(crop.get("x1", 0)),
                y1=float(crop.get("y1", 0)),
                x2=float(crop.get("x2", 1)),
                y2=float(crop.get("y2", 1)),
            )
        except (ValueError, TypeError) as e:
            logger.warning(f"Invalid crop data for image {image.id}: {e}")
            return None

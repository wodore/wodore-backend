"""
Provider for Mapillary images.
TODO: Implement full Mapillary API integration.
"""

import logging

from .base import ImageProvider, ImageResult
from .schemas import GeoPlaceSchema

logger = logging.getLogger(__name__)


class MapillaryProvider(ImageProvider):
    """
    Provider for Mapillary images.
    TODO: Implement full Mapillary API integration.
    """

    source = "mapillary"
    cache_ttl = 7 * 24 * 3600  # 7 days
    priority = 5

    async def fetch(
        self,
        places: list[GeoPlaceSchema],
        lat: float,
        lon: float,
        radius: float,
        limit: int = 100,
        update_cache: bool = False,
    ) -> list[ImageResult]:
        """Fetch images from Mapillary - TODO: Not yet implemented."""
        logger.debug("MapillaryProvider: Not yet implemented")
        return []

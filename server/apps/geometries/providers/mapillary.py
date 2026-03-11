"""
Provider for Mapillary images.
TODO: Implement full Mapillary API integration.
"""

import logging
from typing import Any

from .base import ImageProvider, ImageResult

logger = logging.getLogger(__name__)


class MapillaryProvider(ImageProvider):
    """
    Provider for Mapillary images.
    TODO: Implement full Mapillary API integration.
    """

    source = "mapillary"
    cache_ttl = 12 * 60 * 60  # 12 hours
    priority = 4

    async def fetch(
        self,
        geoplaces: list[Any],
        lat: float,
        lon: float,
        radius: float,
        limit: int = 100,
    ) -> list[ImageResult]:
        """Fetch images from Mapillary - TODO: Not yet implemented."""
        logger.info("MapillaryProvider: Not yet implemented")
        return []

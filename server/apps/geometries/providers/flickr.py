"""
Provider for Flickr images.
TODO: Implement full Flickr API integration.
"""

import logging
from typing import Any

from .base import ImageProvider, ImageResult

logger = logging.getLogger(__name__)


class FlickrProvider(ImageProvider):
    """
    Provider for Flickr images.
    TODO: Implement full Flickr API integration.
    """

    source = "flickr"
    cache_ttl = 24 * 60 * 60  # 24 hours
    priority = 5

    async def fetch(
        self,
        geoplaces: list[Any],
        lat: float,
        lon: float,
        radius: float,
        limit: int = 100,
    ) -> list[ImageResult]:
        """Fetch images from Flickr - TODO: Not yet implemented."""
        logger.info("FlickrProvider: Not yet implemented")
        return []

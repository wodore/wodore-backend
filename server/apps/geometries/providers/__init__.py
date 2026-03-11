"""
Image provider system for aggregating images from multiple sources.
"""

from .base import (
    ImageProvider,
    ImageResult,
    ProviderRegistry,
    provider_registry,
    fetch_images_for_place,
    fetch_images_from_providers,
    deduplicate_images,
    post_process_images,
    PRECISION_LEVELS,
)

from .wodore import WodoreProvider
from .wikidata import WikidataProvider
from .flickr import FlickrProvider
from .mapillary import MapillaryProvider
from .panoramax import PanoramaxProvider
from .camptocamp import CamptocampProvider
from .wikimedia_commons import WikimediaCommonsProvider

__all__ = [
    "ImageProvider",
    "ImageResult",
    "ProviderRegistry",
    "provider_registry",
    "fetch_images_for_place",
    "fetch_images_from_providers",
    "deduplicate_images",
    "post_process_images",
    "PRECISION_LEVELS",
    "WodoreProvider",
    "WikidataProvider",
    "FlickrProvider",
    "MapillaryProvider",
    "PanoramaxProvider",
    "CamptocampProvider",
    "WikimediaCommonsProvider",
]

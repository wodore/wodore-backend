"""
Image provider system for aggregating images from multiple sources.
"""

from server.apps.reviews.images import MangroveProvider

from .base import (
    PRECISION_LEVELS,
    ImageProvider,
    ImageResult,
    ProviderRegistry,
    deduplicate_images,
    fetch_images_for_place,
    fetch_images_from_providers,
    post_process_images,
    provider_registry,
    run_async,
)
from .camptocamp import CamptocampProvider
from .mapillary import MapillaryProvider
from .panoramax import PanoramaxProvider
from .refugesinfo import RefugesInfoProvider
from .wikimedia_commons import WikimediaCommonsProvider
from .wodore import WodoreProvider

__all__ = [
    "PRECISION_LEVELS",
    "CamptocampProvider",
    "ImageProvider",
    "ImageResult",
    "MapillaryProvider",
    "PanoramaxProvider",
    "ProviderRegistry",
    "RefugesInfoProvider",
    "WikimediaCommonsProvider",
    "WodoreProvider",
    "MangroveProvider",
    "deduplicate_images",
    "fetch_images_for_place",
    "fetch_images_from_providers",
    "post_process_images",
    "provider_registry",
    "run_async",
]

# Note: WikidataProvider replaced by WikimediaCommonsProvider (more comprehensive)
# Note: FlickrProvider removed (requires premium API key)


#: Review photos from the Mangrove dataset (reviews app).
provider_registry.register(MangroveProvider())

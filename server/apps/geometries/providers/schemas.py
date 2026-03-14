"""
Unified schema for geographical places.

This module provides a unified interface for working with both Hut and GeoPlace models,
allowing providers to access source IDs (like Wikidata QID, refuges.info ID) in a
consistent way regardless of the underlying model.
"""

from dataclasses import dataclass, field
from typing import Any, Optional
from logging import getLogger

from asgiref.sync import sync_to_async

logger = getLogger(__name__)


@dataclass
class Source:
    """
    Represents a data source for a geographical place.

    Attributes:
        slug: The source identifier (e.g., "wikidata", "osm", "refuges")
        source_id: The external ID from this source (e.g., "Q123456", "12345")
        source_data: Optional full source data dict for additional metadata
        priority: Lower values = higher priority (used when multiple sources have the same slug)
    """

    slug: str
    source_id: Optional[str] = None
    source_data: Optional[dict] = None
    priority: int = 10

    def __repr__(self) -> str:
        return f"Source(slug={self.slug!r}, source_id={self.source_id!r})"


@dataclass
class GeoPlaceSchema:
    """
    Unified schema for geographical places (works for both Hut and GeoPlace models).

    This class provides a consistent interface that providers can use to access
    place information and source IDs without caring about the underlying model structure.

    Attributes:
        slug: Unique identifier for the place
        name: Place name
        lat: Latitude
        lon: Longitude
        id: Database ID (optional, for API responses)
        sources: List of Source objects with external IDs
    """

    slug: str
    name: str
    lat: float
    lon: float
    id: int | None = None  # Database ID (optional, not used by providers)
    sources: list[Source] = field(default_factory=list)

    def __repr__(self) -> str:
        return f"GeoPlaceSchema(slug={self.slug!r}, name={self.name!r}, sources={len(self.sources)})"

    def get_source_id(self, slug: str) -> Optional[str]:
        """
        Get the source_id for a given source slug.

        If multiple sources have the same slug, returns the one with highest priority
        (lowest priority number).

        Args:
            slug: The source slug to look up (e.g., "wikidata", "refuges", "osm")

        Returns:
            The source_id if found, None otherwise
        """
        # Filter sources by slug and sort by priority (ascending)
        matching_sources = sorted(
            [s for s in self.sources if s.slug == slug], key=lambda s: s.priority
        )

        if matching_sources:
            source_id = matching_sources[0].source_id
            logger.debug(f"  get_source_id({slug!r}) for {self.slug}: {source_id}")
            return source_id

        logger.debug(f"  get_source_id({slug!r}) for {self.slug}: not found")
        return None

    def get_wikidata_qid(self) -> Optional[str]:
        """
        Convenience method to get the Wikidata QID from any available source.

        Checks multiple sources in priority order:
        1. Direct "wikidata" source
        2. "osm" source (stores QID in tags.wikidata)
        3. Any other source with source_data containing tags.wikidata

        Returns:
            The Wikidata QID if found, None otherwise
        """
        # First try direct wikidata source
        qid = self.get_source_id("wikidata")
        if qid:
            logger.debug(
                f"  get_wikidata_qid for {self.slug}: found in wikidata source: {qid}"
            )
            return qid

        # Try OSM source (QID stored in source_data.tags.wikidata)
        osm_source = self.get_source("osm") or self.get_source("openstreetmap")
        if osm_source and osm_source.source_data:
            tags = osm_source.source_data.get("tags")
            if tags and isinstance(tags, dict):
                qid = tags.get("wikidata")
                if qid:
                    logger.debug(
                        f"  get_wikidata_qid for {self.slug}: found in OSM tags: {qid}"
                    )
                    return qid

        # Check all sources for tags.wikidata
        for source in self.sources:
            if source.source_data and isinstance(source.source_data, dict):
                tags = source.source_data.get("tags")
                if tags and isinstance(tags, dict):
                    qid = tags.get("wikidata")
                    if qid:
                        logger.debug(
                            f"  get_wikidata_qid for {self.slug}: found in {source.slug}.tags: {qid}"
                        )
                        return qid

        logger.debug(f"  get_wikidata_qid for {self.slug}: not found")
        return None

    def get_source(self, slug: str) -> Optional[Source]:
        """
        Get the Source object for a given slug.

        Args:
            slug: The source slug to look up

        Returns:
            The Source object if found, None otherwise
        """
        matching_sources = sorted(
            [s for s in self.sources if s.slug == slug], key=lambda s: s.priority
        )

        if matching_sources:
            return matching_sources[0]
        return None


def geoplace_to_schema(geoplace: Any) -> GeoPlaceSchema:
    """
    Convert a GeoPlace model instance to GeoPlaceSchema.

    Args:
        geoplace: GeoPlace model instance with source associations prefetched

    Returns:
        GeoPlaceSchema with sources extracted from source_associations
    """
    sources = []

    # Extract sources from source_associations
    # This should be prefetched in the query for efficiency
    if hasattr(geoplace, "source_associations"):
        for assoc in geoplace.source_associations.all():
            source = Source(
                slug=assoc.organization.slug,
                source_id=assoc.source_id,
                source_data=assoc.extra or {},
                priority=assoc.priority,
            )
            sources.append(source)

    # Extract OSM data from osm_tags if available
    if geoplace.osm_tags:
        # Check if there's an OSM organization source
        has_osm_org = any(s.slug in ["osm", "openstreetmap"] for s in sources)
        if not has_osm_org and geoplace.osm_tags:
            # Add OSM tags as a source
            osm_source = Source(
                slug="osm",
                source_id=geoplace.osm_tags.get("id"),
                source_data={"tags": geoplace.osm_tags},
                priority=20,
            )
            sources.append(osm_source)

    return GeoPlaceSchema(
        id=geoplace.id,  # Include database ID
        slug=geoplace.slug or "",
        name=geoplace.name_i18n,
        lat=geoplace.location.y,
        lon=geoplace.location.x,
        sources=sources,
    )


def hut_to_schema(hut: Any) -> GeoPlaceSchema:
    """
    Convert a Hut model instance to GeoPlaceSchema.

    Args:
        hut: Hut model instance with hut_sources prefetched

    Returns:
        GeoPlaceSchema with sources extracted from hut_sources
    """
    sources = []

    # Extract sources from hut_sources
    # This should be prefetched in the query for efficiency
    if hasattr(hut, "hut_sources"):
        for hut_source in hut.hut_sources.all():
            # Build source_data dict
            source_data = {}
            if hut_source.source_data:
                source_data = hut_source.source_data
            if hut_source.source_properties:
                source_data.update(hut_source.source_properties)

            source = Source(
                slug=hut_source.organization.slug,
                source_id=hut_source.source_id,
                source_data=source_data,
                priority=10,  # Default priority for hut sources
            )
            sources.append(source)

    return GeoPlaceSchema(
        id=hut.id,  # Include database ID
        slug=hut.slug or "",
        name=hut.name_i18n,
        lat=hut.location.y,
        lon=hut.location.x,
        sources=sources,
    )


async def geoplace_to_schema_async(geoplace: Any) -> GeoPlaceSchema:
    """
    Async version of geoplace_to_schema.

    Wraps the synchronous conversion in sync_to_async.

    Args:
        geoplace: GeoPlace model instance

    Returns:
        GeoPlaceSchema with sources extracted from source_associations
    """
    return await sync_to_async(geoplace_to_schema)(geoplace)


async def hut_to_schema_async(hut: Any) -> GeoPlaceSchema:
    """
    Async version of hut_to_schema.

    Wraps the synchronous conversion in sync_to_async.

    Args:
        hut: Hut model instance

    Returns:
        GeoPlaceSchema with sources extracted from hut_sources
    """
    return await sync_to_async(hut_to_schema)(hut)


async def convert_places_to_schemas(
    geoplaces: list[Any] | None = None,
    huts: list[Any] | None = None,
) -> list[GeoPlaceSchema]:
    """
    Convert a mixed list of GeoPlaces and Huts to GeoPlaceSchema objects.

    Optimized to use a single sync_to_async call for all conversions
    instead of sequential calls for each place.

    Args:
        geoplaces: List of GeoPlace instances (with source_associations prefetched)
        huts: List of Hut instances (with hut_sources prefetched)

    Returns:
        List of GeoPlaceSchema objects from both inputs
    """

    def convert_all():
        """Convert all places in a single thread pool call."""
        schemas = []

        # Convert geoplaces
        if geoplaces:
            for geoplace in geoplaces:
                schemas.append(geoplace_to_schema(geoplace))

        # Convert huts
        if huts:
            for hut in huts:
                schemas.append(hut_to_schema(hut))

        return schemas

    # Use single sync_to_async call for all conversions
    return await sync_to_async(convert_all)()

"""
Schemas for GeoPlace API endpoints.
"""

from ninja import Field, ModelSchema
from pydantic import computed_field

from server.apps.categories.models import Category
from server.apps.geometries.models import GeoPlace


class CategorySchema(ModelSchema):
    """Schema for category information in GeoPlace responses."""

    name: str | None = Field(..., alias="name_i18n")
    description: str | None = Field(None, alias="description_i18n")

    class Meta:
        model = Category
        fields = ("slug", "name", "description")


class GeoPlaceBaseSchema(ModelSchema):
    """Base schema for GeoPlace with essential fields."""

    name: str = Field(..., alias="name_i18n")
    place_type: CategorySchema

    class Meta:
        model = GeoPlace
        fields = (
            "id",
            "name",
            "place_type",
            "country_code",
            "elevation",
            "importance",
        )


class GeoPlaceSearchSchema(GeoPlaceBaseSchema):
    """Schema for search results with location coordinates."""

    @computed_field
    @property
    def latitude(self) -> float | None:
        """Extract latitude from location point."""
        return self.location.y if self.location else None

    @computed_field
    @property
    def longitude(self) -> float | None:
        """Extract longitude from location point."""
        return self.location.x if self.location else None

    class Meta:
        model = GeoPlace
        fields = (
            "id",
            "name",
            "place_type",
            "country_code",
            "elevation",
            "importance",
        )


class GeoPlaceDetailSchema(GeoPlaceSearchSchema):
    """Detailed schema for GeoPlace with all public fields."""

    parent: GeoPlaceBaseSchema | None = None

    class Meta:
        model = GeoPlace
        fields = (
            "id",
            "name",
            "place_type",
            "country_code",
            "elevation",
            "importance",
            "parent",
            "is_active",
            "is_public",
        )


class GeoPlaceNearbySchema(GeoPlaceSearchSchema):
    """Schema for nearby places with distance information."""

    distance: float | None = None  # Distance in meters, set by the query

    class Meta:
        model = GeoPlace
        fields = (
            "id",
            "name",
            "place_type",
            "country_code",
            "elevation",
            "importance",
        )

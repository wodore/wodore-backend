"""
Schemas for GeoPlace API endpoints.
"""

from hut_services import LocationSchema
from ninja import Field, ModelSchema

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
    country_code: str

    @staticmethod
    def resolve_country_code(obj):
        """Convert Country object to string code."""
        return str(obj.country_code) if obj.country_code else None

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

    location: LocationSchema
    score: float | None = None

    @staticmethod
    def resolve_score(obj):
        """Get search similarity score from the dynamically attached attribute."""
        return getattr(obj, "similarity", None)

    class Meta:
        model = GeoPlace
        fields = (
            "id",
            "name",
            "place_type",
            "country_code",
            "elevation",
            "importance",
            "location",
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


class GeoPlaceNearbySchema(GeoPlaceBaseSchema):
    """Schema for nearby places with distance information."""

    location: LocationSchema
    distance: float | None = None

    @staticmethod
    def resolve_distance(obj):
        """Get distance in meters from the dynamically attached attribute."""
        return getattr(obj, "distance_m", None)

    class Meta:
        model = GeoPlace
        fields = (
            "id",
            "name",
            "place_type",
            "country_code",
            "elevation",
            "importance",
            "location",
        )

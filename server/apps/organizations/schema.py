from typing import Any

from django.conf import settings
from django.http import HttpRequest
from ninja import Field, ModelSchema, Schema

from .models import Organization


class OrganizationSearchSchema(Schema):
    """Schema for organization in search results."""

    slug: str
    name: str | None = None
    logo: str | None = None

    @staticmethod
    def resolve_logo(obj: Any, request: HttpRequest | None = None) -> str | None:
        """Get logo URL."""
        if not hasattr(obj, "logo") or not obj.logo:
            return None
        path = str(obj.logo)
        if path.startswith("http"):
            return path
        media_url = getattr(settings, "MEDIA_URL", "/media/")
        if request and not media_url.startswith("http"):
            media_url = request.build_absolute_uri(media_url)
        return f"{media_url}{path}"


class OrganizationSourceIdSlugSchema(Schema):
    """Schema for organization with source ID - slug only version."""

    source: str
    source_id: str | None = None


class OrganizationSourceIdDetailSchema(Schema):
    """Schema for organization with source ID - full details version."""

    source: OrganizationSearchSchema
    source_id: str | None = None


class OrganizationUpdate(ModelSchema):
    slug: str | None = None
    # name_i18n: TranslationSchema | None = Field(None, alias="name")
    # order: int | None = None

    class Meta:
        model = Organization
        fields = ["slug"]

    #    fields = Organization.get_fields_update()
    #    fields_optional = Organization.get_fields_update()  # .remove("name")


class OrganizationOptional(ModelSchema):
    # name_i18n: str | TranslationSchema | None = None
    name: str | None = Field(..., alias="name_i18n")
    fullname: str | None = Field(None, alias="fullname_i18n")
    description: str | None = Field(None, alias="description_i18n")
    attribution: str | None = Field(None, alias="attribution_i18n")
    url: str | None = Field(None, alias="url_i18n")
    config: dict | None = Field(None)
    props_schema: dict | None = Field(None)
    order: int | None = None

    class Meta:
        model = Organization
        fields = Organization.get_fields_all()
        fields_optional = (
            f
            for f in Organization.get_fields_all()
            if f not in ("config", "props_schema")
        )  # .remove("name")


class OrganizationCreate(ModelSchema):
    class Meta:
        model = Organization
        fields = Organization.get_fields_in()

"""Pydantic API schemas for organizations (plain models, dmr-compatible)."""

from typing import Any

import pydantic
from pydantic import AliasChoices, Field, field_validator

from django.conf import settings
from django.http import HttpRequest

from .models import Organization


class OrganizationSearchSchema(pydantic.BaseModel):
    """Schema for organization in search results."""

    model_config = pydantic.ConfigDict(from_attributes=True)

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


class OrganizationSourceIdSlugSchema(pydantic.BaseModel):
    """Schema for organization with source ID - slug only version."""

    source: str
    source_id: str | None = None


class OrganizationSourceIdDetailSchema(pydantic.BaseModel):
    """Schema for organization with source ID - full details version."""

    source: OrganizationSearchSchema
    source_id: str | None = None


class OrganizationOptional(pydantic.BaseModel):
    """Organization with every field optional (include/exclude base).

    Validation reads the localized ``*_i18n`` attributes
    (modeltranslation/djjmt descriptors resolve the active language);
    serialization emits the plain field names (``name`` etc.).
    """

    model_config = pydantic.ConfigDict(from_attributes=True)

    slug: str | None = None
    name: str | None = Field(..., validation_alias=AliasChoices("name_i18n", "name"))
    fullname: str | None = Field(None, validation_alias="fullname_i18n")
    description: str | None = Field(None, validation_alias="description_i18n")
    url: str | None = Field(None, validation_alias="url_i18n")
    attribution: str | None = Field(None, validation_alias="attribution_i18n")
    link_hut_pattern: str | None = None
    logo: str | None = None
    is_active: bool | None = None
    is_public: bool | None = None
    color_light: str | None = None
    color_dark: str | None = None
    config: dict | None = None
    props_schema: dict | None = None
    order: int | None = None

    class Meta:
        # Used by api.query.include_set to attach {field}_i18n companions.
        model = Organization

    @field_validator("logo", mode="before")
    @classmethod
    def _logo_to_str(cls, value: object) -> str | None:
        """ImageFieldFile -> path string (former ninja ModelSchema coercion)."""
        return str(value) if value else None

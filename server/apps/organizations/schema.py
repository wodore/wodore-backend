from typing import Any
from .models import Organization

from ninja import ModelSchema

from ..djjmt.fields import TranslationSchema


class OrganizationUpdate(ModelSchema):
    slug: str | None = None
    name: dict[str, Any] | None = None
    order: int | None = None

    class Meta:
        model = Organization
        fields = Organization.get_fields_update()
        fields_optional = Organization.get_fields_update().remove("name")


class OrganizationOptional(ModelSchema):
    name: str | TranslationSchema | None = None
    description: str | TranslationSchema | None = None
    order: int | None = None

    class Meta:
        model = Organization
        fields = Organization.get_fields_all()
        fields_optional = Organization.get_fields_all().remove("name")


class OrganizationCreate(ModelSchema):
    class Meta:
        model = Organization
        fields = Organization.get_fields_in()

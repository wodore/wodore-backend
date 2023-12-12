from server.apps.djjmt.fields import TranslationSchema
from ninja import ModelSchema

from .models import Organization


class OrganizationUpdate(ModelSchema):
    slug: str | None = None
    name: TranslationSchema | None = None
    order: int | None = None

    class Meta:
        model = Organization
        fields = Organization.get_fields_update()
        fields_optional = Organization.get_fields_update().remove("name")


class OrganizationOptional(ModelSchema):
    name: str | TranslationSchema | None = None
    # description: str | TranslationSchema | None = None
    order: int | None = None

    class Meta:
        model = Organization
        fields = Organization.get_fields_all()
        fields_optional = Organization.get_fields_all().remove("name")


class OrganizationCreate(ModelSchema):
    class Meta:
        model = Organization
        fields = Organization.get_fields_in()

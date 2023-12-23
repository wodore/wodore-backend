from ninja import Field, ModelSchema

from server.apps.translations import TranslationSchema

from .models import Organization


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
            f for f in Organization.get_fields_all() if f not in ("config", "props_schema")
        )  # .remove("name")


class OrganizationCreate(ModelSchema):
    class Meta:
        model = Organization
        fields = Organization.get_fields_in()

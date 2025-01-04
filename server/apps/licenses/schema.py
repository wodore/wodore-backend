from ninja import Field, ModelSchema

from .models import License


class LicenseUpdate(ModelSchema):
    slug: str | None = None
    # name_i18n: TranslationSchema | None = Field(None, alias="name")
    # order: int | None = None

    class Meta:
        model = License
        fields = ("slug",)

    #    fields = Organization.get_fields_update()
    #    fields_optional = Organization.get_fields_update()  # .remove("name")


class LicenseOptional(ModelSchema):
    # name_i18n: str | TranslationSchema | None = None
    name: str | None = Field(..., alias="name_i18n")
    fullname: str | None = Field(None, alias="fullname_i18n")
    description: str | None = Field(None, alias="description_i18n")
    link: str | None = Field(None, alias="url_i18n")
    order: int | None = None

    class Meta:
        model = License
        fields = License.get_fields_all()
        fields_optional = (
            f for f in License.get_fields_all() if f not in ("config", "props_schema")
        )  # .remove("name")


class OrganizationCreate(ModelSchema):
    class Meta:
        model = License
        fields = License.get_fields_in()

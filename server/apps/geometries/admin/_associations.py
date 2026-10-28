"""Admin registration for association and detail models.

These models are primarily managed via inlines on their parent GeoPlace admin,
but are registered standalone to satisfy the model-admin check and allow
direct inspection of the data.
"""

from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from unfold.decorators import display

from server.apps.manager.admin import ModelAdmin

from ..models import (
    AdminDetail,
    CategoryExtraSchema,
    GeoPlaceCategory,
    GeoPlaceExternalLink,
    GeoPlaceImageAssociation,
    GeoPlaceParty,
    GeoPlaceSourceAssociation,
)


@admin.register(GeoPlaceParty)
class GeoPlacePartyAdmin(ModelAdmin):
    list_display = ("geo_place", "party", "role", "order")
    list_filter = ("role",)
    search_fields = ("geo_place__name", "geo_place__slug", "party__slug")
    autocomplete_fields = ("geo_place", "party", "role")


@admin.register(AdminDetail)
class AdminDetailAdmin(ModelAdmin):
    list_display = ("geo_place", "admin_level", "population", "postal_code", "iso_code")
    list_filter = ("admin_level",)
    search_fields = ("geo_place__name", "geo_place__slug")
    autocomplete_fields = ("geo_place",)


@admin.register(CategoryExtraSchema)
class CategoryExtraSchemaAdmin(ModelAdmin):
    """Extra-attribute schemas — seeded from code, evolved in admin.

    ``Organization.props_schema`` parity: the JSON Schema describing
    a category subtree's association ``extra`` keys. Changing a
    schema takes effect on the next write (old rows are not
    retro-checked) — evolve additively.
    """

    list_display = ("category", "schema_preview", "modified")
    search_fields = ("category__slug", "category__identifier")
    autocomplete_fields = ("category",)

    @display(description=_("Schema"))
    def schema_preview(self, obj: CategoryExtraSchema) -> str:
        import json

        text = json.dumps(obj.schema)
        return f"{text[:80]}…" if len(text) > 80 else text


@admin.register(GeoPlaceCategory)
class GeoPlaceCategoryAdmin(ModelAdmin):
    list_display = ("geo_place", "category", "classifier")
    list_filter = ("category__parent",)
    search_fields = ("geo_place__name", "geo_place__slug", "category__slug")
    autocomplete_fields = ("geo_place", "category", "classifier")


@admin.register(GeoPlaceExternalLink)
class GeoPlaceExternalLinkAdmin(ModelAdmin):
    list_display = ("geo_place", "external_link", "order")
    search_fields = ("geo_place__name", "geo_place__slug")
    autocomplete_fields = ("geo_place", "external_link")


@admin.register(GeoPlaceImageAssociation)
class GeoPlaceImageAssociationAdmin(ModelAdmin):
    list_display = ("geo_place", "image", "score")
    search_fields = ("geo_place__name", "geo_place__slug")
    autocomplete_fields = ("geo_place", "image")


@admin.register(GeoPlaceSourceAssociation)
class GeoPlaceSourceAssociationAdmin(ModelAdmin):
    list_display = (
        "geo_place",
        "organization",
        "source_id",
        "update_policy",
        "delete_policy",
    )
    list_filter = ("organization", "update_policy", "delete_policy")
    search_fields = ("geo_place__name", "geo_place__slug", "source_id")
    autocomplete_fields = ("geo_place", "organization")

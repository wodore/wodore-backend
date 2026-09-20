"""Admin registration for association and detail models.

These models are primarily managed via inlines on their parent GeoPlace admin,
but are registered standalone to satisfy the model-admin check and allow
direct inspection of the data.
"""

from django.contrib import admin

from server.apps.manager.admin import ModelAdmin

from ..models import (
    AdminDetail,
    GeoPlaceCategory,
    GeoPlaceExternalLink,
    GeoPlaceImageAssociation,
    GeoPlaceSourceAssociation,
)


@admin.register(AdminDetail)
class AdminDetailAdmin(ModelAdmin):
    list_display = ("geo_place", "admin_level", "population", "postal_code", "iso_code")
    list_filter = ("admin_level",)
    search_fields = ("geo_place__name", "geo_place__slug")
    autocomplete_fields = ("geo_place",)


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
    list_display = ("geo_place", "image", "order")
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

# Models
from typing import ClassVar

from cloudinary import CloudinaryImage

from django.contrib import admin
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

from unfold.decorators import display

from server.apps.imagefocus import ImageFocusAdminMixin
from server.apps.manager.admin import ModelAdmin
from server.apps.translations.forms import required_i18n_fields_form_factory
from server.core.utils import text_shorten_html

# try:
#    from unfold.admin import ModelAdmin
# except ModuleNotFoundError:
#    from django.contrib.admin import ModelAdmin
from .forms import ImageAdminFieldsets

# Register your models here.
from .models import Image


@admin.register(Image)
# class OrganizationAdmin(ActiveLanguageMixin, admin.ModelAdmin[Organization]):
class ImageAdmin(ImageFocusAdminMixin, ModelAdmin):
    """Admin panel example for ``BlogPost`` model."""

    form = required_i18n_fields_form_factory("caption")
    fieldsets = ImageAdminFieldsets
    view_on_site = True
    radio_fields: ClassVar = {"review_status": admin.HORIZONTAL}
    list_display = (
        "thumb",
        "caption_short",
        "license_summary",
        "source",
        "review_tag",
    )
    list_display_links = ("thumb",)
    search_fields = ("author", "caption_i18n")
    list_filter = ("source_org", "license", "review_status", "uploaded_by_user", "uploaded_by_anonym")
    readonly_fields = (
        "id",
        "caption_i18n",
        "created",
        "modified",
        # "image_meta",
    )

    def save_model(self, request, obj, form, change):
        if not obj.uploaded_by_user:
            obj.uploaded_by_user = request.user
        super().save_model(request, obj, form, change)

    @display(description="license", header=True)
    def license_summary(self, obj):
        return mark_safe(
            f'<a href={obj.license.link_i18n} target="_blank">{obj.license.name_i18n}</a>'
        ), text_shorten_html(obj.license.fullname_i18n, textsize="xs", width=60)

    @display(description="Source", header=True)
    def source(self, obj):
        src = []
        if obj.author:
            src.append(obj.author)
        if obj.source_org:
            src.append(f'<i><a href={obj.source_org.url} target="_blank">{obj.source_org.name_i18n}</a></i>')
        if obj.source_url:
            link = f'<a href={obj.source_url} target="_blank">{text_shorten_html(obj.source_url, textsize="sm", width=40)}</a>'
        else:
            link = ""
        return mark_safe(", ".join(src)), mark_safe(link)

    @display(description="Caption")
    def caption_short(self, obj):
        return text_shorten_html(obj.caption_i18n, textsize="xs", width=60, on_word=True)

    def thumb(self, obj):  # new
        try:
            obj.image.url  # does not work if removed?
            img = CloudinaryImage(obj.image.name).image(
                radius=0,
                border="1px_solid_rgb:000000",
                gravity="custom",
                width=120,
                height=60,
                crop="fill",
                fetch_format="auto",
            )
        except Exception as e:
            img = "Missing"
        return mark_safe(img)

    @display(
        description=_("Status"),
        ordering="status",
        label={
            Image.ReviewStatusChoices.approved: "success",
            Image.ReviewStatusChoices.pending: "warning",  # green
            Image.ReviewStatusChoices.rejected: "info",
            # Image.ReviewStatusChoices.disabled: "info",
        },
    )
    def review_tag(self, obj):
        return obj.review_status

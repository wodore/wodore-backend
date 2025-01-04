# Models
import contextlib
from typing import ClassVar

# from cloudinary import CloudinaryImage
with contextlib.suppress(ModuleNotFoundError):
    from django_stubs_ext import QuerySetAny

# from tinymce.widgets import TinyMCE
# from simplemde.widgets import SimpleMDEEditor
from django.contrib import admin
from django.http import HttpRequest
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

from unfold.decorators import display

from server.apps.manager.admin import ModelAdmin
from server.apps.translations.forms import required_i18n_fields_form_factory
from server.core.utils import text_shorten_html

# try:
#    from unfold.admin import ModelAdmin
# except ModuleNotFoundError:
#    from django.contrib.admin import ModelAdmin
from .forms import ImageAdminFieldsets, ImageTagAdminFieldsets

# Register your models here.
from .models import Image, ImageTag
from .transfomer import ImagorImage


@admin.register(ImageTag)
# class OrganizationAdmin(ActiveLanguageMixin, admin.ModelAdmin[Organization]):
class ImageTagAdmin(ModelAdmin):
    """Admin panel example for ``BlogPost`` model."""

    form = required_i18n_fields_form_factory("name")
    fieldsets = ImageTagAdminFieldsets
    search_fields = ("slug", "name_i18n")
    list_display = ("slug", "name_i18n", "color_tag")
    readonly_fields = (
        "name_i18n",
        "created",
        "modified",
        # "image_meta",
    )

    def show_color(self, value, width=32, height=16, radius=4):
        return mark_safe(
            f'<div style="background-color:{value};border-radius:{radius}px;min-height:{height}px;min-width:{width}px;max-height:{height}px;max-width:{width}px"></div>'
        )

    @display(description=_("Color"))
    def color_tag(self, obj):
        return self.show_color(obj.color)


@admin.register(Image)
# class OrganizationAdmin(ActiveLanguageMixin, admin.ModelAdmin[Organization]):
class ImageAdmin(ModelAdmin):
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
        "tag_list",
        "review_tag",
        "show_huts",
    )
    list_display_links = ("thumb", "caption_short")
    search_fields = ("author", "caption_i18n")
    list_filter = (
        "source_org",
        "license",
        "review_status",
        "tags",
        "uploaded_by_user",
        "uploaded_by_anonym",
    )
    readonly_fields = (
        "id",
        "source_url_raw",
        "caption_i18n",
        "created",
        "modified",
        "granted_date",
        "uploaded_date",
        # "image_meta",
    )

    def save_model(self, request, obj, form, change):
        if not obj.uploaded_by_user:
            obj.uploaded_by_user = request.user
        super().save_model(request, obj, form, change)

    def get_queryset(self, request: HttpRequest) -> "QuerySetAny":
        qs = super().get_queryset(request).prefetch_related("tags", "huts")
        return qs.select_related("license", "source_org")

    @display(description="license", header=True)
    def license_summary(self, obj):
        return mark_safe(
            f'<a href={obj.license.link_i18n} target="_blank">{obj.license.name_i18n}</a>'
        ), text_shorten_html(obj.license.fullname_i18n, textsize="xs", width=60)

    @display(description="Tags", header=False)
    def tag_list(self, obj):
        tags = ", ".join([o.slug for o in obj.tags.all()])
        return text_shorten_html(tags, textsize="xs", width=60)

    @display(description="Source", header=True)
    def source(self, obj):
        src = []
        if obj.author:
            src.append(obj.author)
        if obj.source_org:
            src.append(
                f'<i><a href={obj.source_org.url} target="_blank">{obj.source_org.name_i18n}</a></i>'
            )
        if obj.source_url:
            link = f'<a href={obj.source_url} target="_blank">{text_shorten_html(obj.source_url, textsize="sm", width=40)}</a>'
        else:
            link = ""
        return mark_safe(", ".join(src)), mark_safe(link)

    @display(description="Caption")
    def caption_short(self, obj):
        return text_shorten_html(
            obj.caption_i18n, textsize="xs", width=60, on_word=True
        )

    def thumb(self, obj):  # new
        try:
            # obj.image.url  # does not work if removed?
            # img = f'<img width=120 heigh=60 src="{obj.image.url}"/>'
            focal = obj.image_meta.get("focal") if obj.image_meta else None
            if focal:
                focal_str = f"{focal.get('x1',0)}x{focal.get('y1',0)}:{focal.get('x2',1)}x{focal.get('y2',1)}"
            else:
                focal_str = "0x0:1x1"
            crop_start, crop_stop = focal_str.split(":")
            img = (
                ImagorImage(obj.image)
                .transform(
                    size="100x60",
                    focal=focal_str,
                    crop_start=crop_start,
                    crop_stop=crop_stop,
                    round_corner=(10),
                )
                .get_html()
            )
            # img = CloudinaryImage(obj.image.name).image(
            #    radius=0,
            #    border="1px_solid_rgb:000000",
            #    gravity="custom",
            #    width=120,
            #    height=60,
            #    crop="fill",
            #    fetch_format="auto",
            # )
        except Exception as e:
            print(e)
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

    @display(description=_("Huts"))
    def show_huts(self, obj):
        huts = []
        for hut in obj.huts.all():
            hut_url = reverse("admin:huts_hut_change", args=[hut.pk])
            huts.append(f'<small><a href="{hut_url}">{hut.name_i18n}</a></small>')
        huts_str = ", ".join(huts)
        return mark_safe(huts_str)

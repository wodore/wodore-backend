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

from unfold.contrib.filters.admin import ChoicesCheckboxFilter
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

    @display(description=_("Color"))  # pyright: ignore[reportArgumentType]  # _StrPromise vs str: unfold stub gap
    def color_tag(self, obj):
        return self.show_color(obj.color)


@admin.register(Image)
# class OrganizationAdmin(ActiveLanguageMixin, admin.ModelAdmin[Organization]):
class ImageAdmin(ModelAdmin):
    """Admin panel example for ``BlogPost`` model."""

    form = required_i18n_fields_form_factory("caption")
    fieldsets = ImageAdminFieldsets
    view_on_site = True  # pyright: ignore[reportIncompatibleVariableOverride, reportAssignmentType]  # Django admin idiom
    radio_fields: ClassVar = {"review_status": admin.HORIZONTAL}
    list_display = (
        "thumb",
        "caption_short",
        "license_summary",
        "source",
        "serving",
        "quality_display",
        "quick_actions",
        "tag_list",
        "review_tag",
        "show_huts",
    )
    list_display_links = ("thumb", "caption_short")
    search_fields = ("author", "caption_i18n")
    list_filter = (
        "source_org",
        "license",
        (
            "review_status",
            ChoicesCheckboxFilter,
        ),  # Filter by review status with checkboxes
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
        "provider_synced_at",
        "thumbhash_preview",
        "phash",
        "quality_score",
        # "image_meta",
    )

    @display(
        description=_("Serving"),  # pyright: ignore[reportArgumentType]  # _StrPromise vs unfold stub gap
        label={
            "local": "success",
            "external": "warning",
            "none": "danger",
        },
    )
    def serving(self, obj):
        """Where the pixels come from: local file or external pin."""
        if getattr(obj, "image", None):
            return "local"
        if obj.source_url_raw:
            return "external"
        return "none"

    def save_model(self, request, obj, form, change):
        if not obj.uploaded_by_user:  # pyright: ignore[reportAttributeAccessIssue]
            obj.uploaded_by_user = request.user  # pyright: ignore[reportAttributeAccessIssue]
        super().save_model(request, obj, form, change)
        if change:
            # Manual edits (file swap, focal/crop, URLs) change the pixels or
            # the transforms — re-run the assessment stack (phash, quality,
            # thumbhash + variants) so the row serves fresh data.
            try:
                from server.apps.images.assessment import assess_image

                assess_image(obj, force=True)
            except Exception as e:
                self.message_user(request, f"Re-assessment failed: {e}", "warning")

    @display(description=_("ThumbHashes"))
    def thumbhash_preview(self, obj):
        """Decoded ThumbHash placeholders: primary + one per variant."""
        import base64
        import io as _io

        from django.utils.safestring import mark_safe as _safe

        from server.apps.images.assessment import thumbhash_to_image

        entries = []
        if obj.thumbhash:
            entries.append(("full", obj.thumbhash))
        entries.extend(sorted((obj.image_meta or {}).get("thumbhashes", {}).items()))
        if not entries:
            return "—"
        parts = []
        for label, value in entries:
            try:
                image = thumbhash_to_image(value)
                buffer = _io.BytesIO()
                image.save(buffer, format="PNG")
                uri = (
                    "data:image/png;base64,"
                    + base64.b64encode(buffer.getvalue()).decode()
                )
                parts.append(
                    f'<span class="mfu-th"><img src="{uri}" '
                    f'style="image-rendering:pixelated;width:48px;height:auto;'
                    f'border-radius:4px;display:block"/><small>{label}</small></span>'
                )
            except Exception:
                parts.append(
                    f'<span class="mfu-th"><small>{label}: invalid</small></span>'
                )
        return _safe(f'<div class="mfu-th-row">{"".join(parts)}</div>')

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        image_field = form.base_fields.get("image")
        if image_field is not None and hasattr(image_field, "widget"):
            # Pinned external images carry no local file — give the widget the
            # raw source URL so it can preview it, allow focal point selection,
            # and offer the one-click "Download raw" localization. Once a local
            # file exists, the raw UI is not needed.
            raw = (getattr(obj, "source_url_raw", "") or "") if obj else ""
            image_field.widget.raw_url = (
                raw or None if not getattr(obj, "image", None) else None
            )
        return form

    #: Hard cap for the raw-download proxy (bytes).
    DOWNLOAD_RAW_MAX_BYTES = 50 * 1024 * 1024

    class Media:
        css = {"all": ("meta_image_field/css/style.css",)}
        js = ("images/js/quick_actions.js",)

    actions = (
        "approve_selected_images",
        "disable_selected_images",
        "reject_selected_images",
        "download_raw_selected_images",
        "assess_selected_images",
    )

    def get_urls(self):
        from django.urls import path

        urls = super().get_urls()
        custom = [
            path(
                "download-raw/",
                self.admin_site.admin_view(self.download_raw_view),
                name="images_image_download_raw",
            ),
            path(
                "download-raw/<uuid:object_id>/",
                self.admin_site.admin_view(self.download_raw_row_view),
                name="images_image_download_raw_row",
            ),
            path(
                "set-review/<uuid:object_id>/<str:status>/",
                self.admin_site.admin_view(self.set_review_view),
                name="images_image_set_review",
            ),
        ]
        return custom + urls

    def _redirect_back(self, request, fallback="admin:images_image_changelist"):
        """Back to the list (or the page the quick-action was clicked from)."""
        from django.shortcuts import redirect

        referer = request.META.get("HTTP_REFERER")
        if referer and referer.startswith(request.build_absolute_uri("/")[:8]):
            return redirect(referer)
        return redirect(fallback)

    def _fetch_image_bytes(self, url: str) -> tuple[bytes, str]:
        """Download ``url`` (bounded) → (content, content_type)."""
        import requests

        from django.conf import settings

        upstream = requests.get(
            url, headers={"User-Agent": settings.BOT_AGENT}, timeout=30, stream=True
        )
        upstream.raise_for_status()
        content = upstream.raw.read(
            self.DOWNLOAD_RAW_MAX_BYTES + 1, decode_content=True
        )
        if len(content) > self.DOWNLOAD_RAW_MAX_BYTES:
            raise ValueError("Image too large.")
        return content, upstream.headers.get("Content-Type", "image/jpeg")

    def _store_local_file(self, obj, content: bytes, raw_url: str) -> str:
        """Attach downloaded bytes as the image's local file; returns name."""
        from django.core.files.base import ContentFile

        from server.apps.meta_image_field.forms import _sanitize_file_name

        name = _sanitize_file_name(raw_url.split("?")[0].split("/")[-1])
        obj.image.save(name, ContentFile(content), save=True)
        return name

    @staticmethod
    def _is_ajax(request: HttpRequest) -> bool:
        return request.headers.get("x-requested-with") == "XMLHttpRequest"

    def download_raw_row_view(self, request: HttpRequest, object_id):
        """Quick action: download an external pin's raw image and store it.

        AJAX requests get JSON (the changelist updates in place); regular
        requests redirect back with a message.
        """
        from django.contrib import messages
        from django.http import JsonResponse

        def _json(payload, status=200):
            return JsonResponse(payload, status=status)

        ajax = self._is_ajax(request)
        obj = self.get_object(request, object_id)
        if obj is None:
            if ajax:
                return _json({"status": "error", "message": "Image not found."}, 404)
            messages.error(request, "Image not found.")
            return self._redirect_back(request)
        if obj.image or not obj.source_url_raw:
            if ajax:
                return _json(
                    {"status": "error", "message": "No external raw URL."}, 400
                )
            messages.info(request, f"{obj}: no external raw URL to download.")
            return self._redirect_back(request)
        try:
            content, _ctype = self._fetch_image_bytes(obj.source_url_raw)
            name = self._store_local_file(obj, content, obj.source_url_raw)
        except Exception as e:
            if ajax:
                return _json({"status": "error", "message": str(e)}, 502)
            messages.error(request, f"{obj}: download failed ({e}).")
            return self._redirect_back(request)
        if ajax:
            return _json({"status": "ok", "stored": name, "local": True})
        messages.success(request, f"{obj}: stored '{name}' locally.")
        return self._redirect_back(request)

    def set_review_view(self, request: HttpRequest, object_id, status: str):
        """Quick action: set the review status from the changelist."""
        from django.contrib import messages
        from django.http import JsonResponse

        obj = self.get_object(request, object_id)
        valid = [s for s, _lbl in Image.ReviewStatusChoices.choices]
        if obj is None or status not in valid:
            if self._is_ajax(request):
                return JsonResponse(
                    {"status": "error", "message": "Invalid image or status."},
                    status=400,
                )
            messages.error(request, "Invalid image or review status.")
            return self._redirect_back(request)
        obj.review_status = status
        obj.save(update_fields=["review_status"])
        if self._is_ajax(request):
            return JsonResponse({"status": "ok", "review_status": status})
        messages.success(request, f"{obj}: review status set to {status}.")
        return self._redirect_back(request)

    @display(
        description=_("Quality"),  # pyright: ignore[reportArgumentType]  # _StrPromise vs unfold stub gap
        ordering="quality_score",
    )
    def quality_display(self, obj):
        """Technical quality score from assessment (sortable)."""
        if obj.quality_score is None:
            return "—"
        return obj.quality_score

    @display(description="")
    def quick_actions(self, obj):
        """Per-row review buttons + download-raw for external pins."""
        from django.urls import reverse as _reverse

        buttons = []
        for status, icon, title in (
            ("approved", "check_circle", "Approve"),
            ("disabled", "pause_circle", "Disable"),
            ("rejected", "cancel", "Reject"),
        ):
            url = _reverse("admin:images_image_set_review", args=[obj.pk, status])
            buttons.append(
                f'<a href="{url}" class="mfu-qa mfu-qa-{status}" title="{title}">'
                f'<span class="material-symbols-outlined">{icon}</span></a>'
            )
        if not obj.image and obj.source_url_raw:
            url = _reverse("admin:images_image_download_raw_row", args=[obj.pk])
            buttons.append(
                f'<a href="{url}" class="mfu-qa mfu-qa-download" title="Download raw">'
                '<span class="material-symbols-outlined">download</span></a>'
            )
        return mark_safe("".join(buttons))

    @admin.action(description=_("Approve selected images"))
    def approve_selected_images(self, request, queryset):
        updated = queryset.update(review_status=Image.ReviewStatusChoices.approved)
        self.message_user(request, f"Approved {updated} images.")

    @admin.action(description=_("Disable selected images"))
    def disable_selected_images(self, request, queryset):
        updated = queryset.update(review_status=Image.ReviewStatusChoices.disabled)
        self.message_user(request, f"Disabled {updated} images.")

    @admin.action(description=_("Reject selected images"))
    def reject_selected_images(self, request, queryset):
        updated = queryset.update(review_status=Image.ReviewStatusChoices.rejected)
        self.message_user(request, f"Rejected {updated} images.")

    @admin.action(description=_("Download raw for selected images"))
    def download_raw_selected_images(self, request, queryset):
        done = failed = skipped = 0
        for obj in queryset:
            if obj.image or not obj.source_url_raw:
                skipped += 1
                continue
            try:
                content, _ctype = self._fetch_image_bytes(obj.source_url_raw)
                self._store_local_file(obj, content, obj.source_url_raw)
                done += 1
            except Exception:
                failed += 1
        self.message_user(
            request,
            f"Downloaded {done}, skipped {skipped}, failed {failed}.",
        )

    @admin.action(description=_("Assess selected images (quality, phash, thumbhash)"))
    def assess_selected_images(self, request, queryset):
        from server.apps.images.assessment import assess_image

        assessed = skipped = failed = 0
        for obj in queryset:
            try:
                if assess_image(obj):
                    assessed += 1
                else:
                    skipped += 1  # already carries phash + quality
            except Exception:
                failed += 1
        self.message_user(
            request,
            f"Assessed {assessed}, skipped {skipped}, failed {failed}.",
        )

    def download_raw_view(self, request: HttpRequest):
        """Stream an image URL back to the admin widget (same-origin proxy).

        Lets the browser show a download progress bar regardless of the
        origin's CORS policy. SSRF guard: known ``Image.source_url_raw``
        values pass directly; any other URL must resolve to a public host
        (private, loopback, link-local and reserved ranges are refused).
        """
        import requests

        from django.http import HttpResponse, JsonResponse

        url = (request.GET.get("url") or "").strip()
        if not url:
            return JsonResponse({"error": "Missing URL."}, status=400)
        if not self.model.objects.filter(source_url_raw=url).exists():
            if not self._is_public_http_url(url):
                return JsonResponse({"error": "URL not allowed."}, status=400)
        try:
            content, content_type = self._fetch_image_bytes(url)
        except requests.RequestException as e:
            return JsonResponse({"error": f"Upstream fetch failed: {e}"}, status=502)
        except ValueError as e:
            return JsonResponse({"error": str(e)}, status=413)
        response = HttpResponse(content, content_type=content_type)
        response["Content-Disposition"] = 'inline; filename="raw"'
        return response

    @staticmethod
    def _is_public_http_url(url: str) -> bool:
        """http(s) URL whose host resolves to public addresses only."""
        import ipaddress
        import socket
        from urllib.parse import urlsplit

        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            return False
        try:
            infos = socket.getaddrinfo(parts.hostname, None, proto=socket.IPPROTO_TCP)
        except socket.gaierror:
            return False
        addresses = {ipaddress.ip_address(info[4][0]) for info in infos}
        return bool(addresses) and all(
            not (
                addr.is_private
                or addr.is_loopback
                or addr.is_link_local
                or addr.is_reserved
                or addr.is_multicast
            )
            for addr in addresses
        )

    def get_queryset(self, request: HttpRequest) -> "QuerySetAny":
        qs = super().get_queryset(request).prefetch_related("tags", "huts")
        return qs.select_related("license", "source_org")

    @display(description="license", header=True)
    def license_summary(self, obj):
        return mark_safe(
            f'<a href={obj.license.url_i18n} target="_blank">{obj.license.name_i18n}</a>'
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
            # Pinned external images have no local file — fall back to the
            # raw source URL so the list thumbnail works for pins too.
            source = obj.image if getattr(obj, "image", None) else obj.source_url_raw
            focal = obj.image_meta.get("focal") if obj.image_meta else None
            if focal:
                focal_str = f"{focal.get('x1', 0)}x{focal.get('y1', 0)}:{focal.get('x2', 1)}x{focal.get('y2', 1)}"
            else:
                focal_str = "0x0:1x1"
            crop_start, crop_stop = focal_str.split(":")
            img = (
                ImagorImage(source)
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
        description=_("Status"),  # pyright: ignore[reportArgumentType]  # _StrPromise vs str: unfold stub gap
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

    @display(description=_("Huts"))  # pyright: ignore[reportArgumentType]  # _StrPromise vs str: unfold stub gap
    def show_huts(self, obj):
        huts = []
        for hut in obj.huts.all():
            hut_url = reverse("admin:huts_hut_change", args=[hut.pk])
            huts.append(f'<small><a href="{hut_url}">{hut.name_i18n}</a></small>')
        huts_str = ", ".join(huts)
        return mark_safe(huts_str)

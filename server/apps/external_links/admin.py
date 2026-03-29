from __future__ import annotations
from typing import ClassVar

from django.conf import settings
from django.contrib import admin, messages
from django.utils.translation import gettext_lazy as _
from django.utils.safestring import mark_safe
from unfold.decorators import display
from django.utils.html import format_html

from server.apps.manager.admin import ModelAdmin
from server.apps.translations.forms import required_i18n_fields_form_factory
from .models import ExternalLink, ReviewStatus


@admin.register(ExternalLink)
class ExternalLinkAdmin(ModelAdmin):
    """Admin interface for ExternalLink model."""

    form = required_i18n_fields_form_factory("url")

    radio_fields: ClassVar = {"review_status": admin.HORIZONTAL}

    list_display = [
        "identifier_code",
        "label_and_url",
        "link_type",
        "source_logo",
        "health_status_display",
        "review_tag",
        "is_public",
        "is_active",
    ]
    list_filter = [
        "review_status",
        "is_public",
        "is_active",
        "link_type",
        "source",
        "last_checked",
    ]
    search_fields = [
        "identifier",
        "url",
        "url_de",
        "label",
        "label_de",
        "description",
        "description_de",
    ]
    list_editable = ["is_public", "is_active"]
    ordering = ["-created"]
    actions = ["check_health_selected"]

    readonly_fields = (
        "identifier",
        "label_i18n",
        "description_i18n",
        "url_i18n",
        "last_checked",
        "response_code",
        "failure_count",
        "created",
        "modified",
    )

    fieldsets = [
        (
            _("Main Information"),
            {
                "classes": ["tab"],
                "fields": (
                    ("identifier", "label_i18n"),
                    "url_i18n",
                    ("link_type", "source"),
                    ("review_status", "is_public", "is_active"),
                    "review_comment",
                    "description_i18n",
                ),
            },
        ),
        (
            f"{_('Translations')} *",
            {
                "classes": ["tab"],
                "fields": [
                    tuple([f"label_{code}" for code in settings.LANGUAGE_CODES]),
                    *[f"url_{code}" for code in settings.LANGUAGE_CODES],
                    *[f"description_{code}" for code in settings.LANGUAGE_CODES],
                ],
            },
        ),
        (
            _("Link Health"),
            {
                "classes": ["tab"],
                "fields": (("last_checked", "response_code", "failure_count")),
                "description": _(
                    "Health status is automatically checked on save. Use the admin action to manually check selected links."
                ),
            },
        ),
        (
            _("Timestamps"),
            {
                "classes": ["tab"],
                "fields": [
                    ("created", "modified"),
                ],
            },
        ),
    ]

    @display(
        description=_("Review"),
        label={
            ReviewStatus.NEW: "warning",
            ReviewStatus.REVIEW: "info",
            ReviewStatus.WORK: "danger",
            ReviewStatus.DONE: "success",
        },
    )
    def review_tag(self, obj: ExternalLink) -> str:
        """Display review status as colored label."""
        return obj.review_status

    @display(description=_("ID"))
    def identifier_code(self, obj: ExternalLink) -> str:
        """Display identifier wrapped in code tag."""
        return mark_safe(f"<code>{obj.identifier}</code>")

    @display(description=_("Link"), header=True)
    def label_and_url(self, obj: ExternalLink) -> tuple:
        """Display label and clickable URL together."""
        url = obj.url_i18n
        icon = '<span class="material-symbols-outlined" style="font-size:x-small">open_in_new</span>'

        # Truncate URL if too long
        display_url = url
        if len(url) > 100:
            display_url = url[:99] + "..."

        # Make URL clickable
        url_link = mark_safe(
            f'<a class="text-gray-500 text-xs" target="_blank" href="{url}">'
            f"{display_url} {icon}</a>"
        )

        return (obj.label_i18n, url_link)

    @display(description=_("Source"))
    def source_logo(self, obj: ExternalLink) -> str:
        """Display source organization with logo icon."""
        if not obj.source:
            return "-"

        if obj.source.logo:
            return mark_safe(
                f'<img class="inline" src="{settings.MEDIA_URL}{obj.source.logo}" '
                f'width="24px" alt="{obj.source.name_i18n}" title="{obj.source.name_i18n}"/>'
            )

        return obj.source.name_i18n

    @display(description=_("Health"))
    def health_status_display(self, obj: ExternalLink) -> str:
        """Display health status with color indicator."""
        if not obj.last_checked:
            return format_html('<span style="color: gray;">{}</span>', "Not checked")

        if obj.failure_count == 0 and obj.response_code and obj.response_code < 400:
            return format_html(
                '<span style="color: green;">✓ {}</span>', obj.response_code
            )
        elif obj.failure_count > 0:
            return format_html(
                '<span style="color: red;">✗ {} failures</span>', obj.failure_count
            )
        else:
            return format_html(
                '<span style="color: orange;">⚠ {}</span>', obj.response_code
            )

    @admin.action(description=_("Check health of selected links"))
    def check_health_selected(self, request, queryset):
        """Admin action to check health of selected external links."""
        checked = 0
        success = 0
        failed = 0

        for link in queryset:
            result = link.check_health()
            link.save(update_fields=["last_checked", "response_code", "failure_count"])
            checked += 1

            if result.get("success"):
                success += 1
            else:
                failed += 1

        messages.success(
            request,
            _("Checked %(checked)d links: %(success)d OK, %(failed)d failed.")
            % {
                "checked": checked,
                "success": success,
                "failed": failed,
            },
        )

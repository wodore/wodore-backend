from typing import ClassVar

from django.contrib import admin

# Models
# from server.core.utils import text_shorten_html
from django.utils.translation import gettext_lazy as _

from unfold.decorators import display

from server.apps.manager.admin import ModelAdmin

# Register your models here.
from .models import Feedback


@admin.register(Feedback)
# class OrganizationAdmin(ActiveLanguageMixin, admin.ModelAdmin[Organization]):
class FeedbackAdmin(ModelAdmin):
    """Admin panel example for ``Feedback`` model."""

    radio_fields: ClassVar = {"feedback_status": admin.HORIZONTAL}
    fieldsets = [
        (
            _("Feedback"),
            {
                "fields": [
                    ("email", "feedback_status"),
                    "subject",
                    "message",
                    "urls",
                    "get_updates",
                    "feedback_comment",
                ],
            },
        ),
        (
            _("Timestamps"),
            {
                "classes": ["collapse"],
                "fields": [
                    ("created", "modified"),
                ],
            },
        ),
    ]

    view_on_site = True
    list_display = ("email", "subject", "created", "get_updates", "status_tag")
    list_display_links = ("email",)
    list_filter = (
        "email",
        "feedback_status",
        "get_updates",
        "created",
        "modified",
    )
    search_fields = ("email", "message")
    readonly_fields = ("created", "modified")

    @display(
        description=_("Status"),
        ordering="status",
        label={
            # Feedback.FeedbackStatusChoices.review: "info",
            Feedback.FeedbackStatusChoices.done: "success",
            Feedback.FeedbackStatusChoices.new: "warning",  # green
            Feedback.FeedbackStatusChoices.work: "danger",
        },
    )
    def status_tag(self, obj):
        return obj.feedback_status

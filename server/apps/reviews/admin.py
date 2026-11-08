"""Unfold admin for the reviews app."""

import json
import typing as t
from typing import override

from django.contrib import admin
from django.http import HttpRequest, HttpResponse
from django.utils.translation import gettext_lazy as _

from server.apps.manager.admin import ModelAdmin

from .models import ReviewBlacklist, ReviewerKey, ReviewerProfile, SubmittedReview


@admin.register(ReviewerKey)
class ReviewerKeyAdmin(ModelAdmin):
    """Server-held reviewer keys (read-mostly; the JWK stays encrypted)."""

    list_display = ("user", "short_kid", "created")
    search_fields = ("kid", "user__email")
    readonly_fields = ("kid", "created", "modified")

    @admin.display(description=_("Key (start)"))
    def short_kid(self, obj: ReviewerKey) -> str:
        return obj.kid[:50] + "…"

    @override
    def has_add_permission(self, request: HttpRequest) -> bool:
        return False  # minted by the write path only


@admin.register(ReviewerProfile)
class ReviewerProfileAdmin(ModelAdmin):
    """Reviewer display defaults."""

    list_display = ("nickname", "user", "language", "created")
    search_fields = ("nickname", "user__email")


@admin.register(SubmittedReview)
class SubmittedReviewAdmin(ModelAdmin):
    """Append-only relay log (audit/erasure/archival aid)."""

    list_display = (
        "user",
        "hut_slug",
        "action",
        "state",
        "short_signature",
        "iat",
        "created",
    )
    list_filter = ("action", "state", "created")
    search_fields = ("signature", "hut_slug", "user__email")
    readonly_fields = (
        "user",
        "hut_slug",
        "subject",
        "action",
        "state",
        "iat",
        "signature",
        "target_signature",
        "jwt",
        "created",
        "modified",
    )
    actions = ("export_jsonl",)

    @override
    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    @override
    def has_delete_permission(
        self, request: HttpRequest, obj: t.Any | None = None
    ) -> bool:
        return False  # append-only; only the erasure path destroys rows

    @admin.display(description=_("Signature (start)"))
    def short_signature(self, obj: SubmittedReview) -> str:
        return obj.signature[:16] + "…"

    @admin.action(description=_("Export selected rows as JSONL (archival export)"))
    def export_jsonl(self, _request: HttpRequest, queryset: t.Any) -> HttpResponse:
        """The archival/export path (mangrove-client spec): verbatim JWTs."""
        rows = [
            json.dumps(
                {
                    "signature": row.signature,
                    "target_signature": row.target_signature,
                    "action": row.action,
                    "state": row.state,
                    "subject": row.subject,
                    "hut_slug": row.hut_slug,
                    "user": str(row.user_id),
                    "iat": row.iat.isoformat(),
                    "jwt": row.jwt,
                }
            )
            for row in queryset.order_by("created")
        ]
        response = HttpResponse(
            "\n".join(rows) + ("\n" if rows else ""),
            content_type="application/x-ndjson",
        )
        response["Content-Disposition"] = (
            'attachment; filename="reviews-submissions.jsonl"'
        )
        return response


@admin.register(ReviewBlacklist)
class ReviewBlacklistAdmin(ModelAdmin):
    """Local serving blacklist (never mutates upstream data)."""

    list_display = ("short_signature", "reason", "created_by", "created")
    search_fields = ("signature", "reason")
    actions = ("blacklist_signatures",)

    @admin.display(description=_("Signature (start)"))
    def short_signature(self, obj: ReviewBlacklist) -> str:
        return obj.signature[:16] + "…"

    @admin.action(description=_("Blacklist pasted signatures (one per line)"))
    def blacklist_signatures(
        self, request: HttpRequest, _queryset: t.Any
    ) -> HttpResponse | None:
        from django.contrib import messages
        from django.shortcuts import redirect

        pasted = request.POST.get("signatures", "")
        created = 0
        for line in pasted.splitlines():
            signature = line.strip()
            if signature:
                _entry, was_created = ReviewBlacklist.objects.get_or_create(
                    signature=signature,
                    defaults={"created_by": request.user},
                )
                created += int(was_created)
        messages.info(request, _("Blacklisted {} new signature(s).").format(created))
        return redirect("admin:reviews_reviewblacklist_changelist")

"""Shared admin helpers for LLM translation and description assessment.

`LLMAdminMixin` adds changelist actions and change-form buttons that call
the translation service (`translate_instance`) and the quality assessment
service (`assess_instance`) on any model with an ``i18n`` TranslationField.
`DescriptionQualityFilter` is the range filter for the quality score.
"""

import typing as t

from django.contrib import admin, messages
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.http import HttpRequest, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect
from django.urls import path, reverse
from django.utils.translation import gettext_lazy as _

from unfold.decorators import action, display

from server.apps.translations.llm import (
    TranslationClient,
    TranslationError,
    translations_api_enabled,
)
from server.apps.translations.service import assess_instance, translate_instance

# Max object names listed per outcome in a single admin message.
_MAX_LISTED = 8


class DescriptionQualityFilter(admin.SimpleListFilter):
    """Range filter for the LLM description quality score."""

    title = _("description quality")  # pyright: ignore[reportAssignmentMismatch]  # SimpleListFilter API
    parameter_name = "description_quality_range"

    def lookups(self, request, model_admin):
        return (
            ("low", _("low (1-3)")),
            ("mid", _("adequate (4-6)")),
            ("good", _("good (7-10)")),
            ("none", _("unscored")),
        )

    def queryset(self, request, queryset):
        value = self.value()
        if value == "low":
            return queryset.filter(description_quality__lte=3)
        if value == "mid":
            return queryset.filter(
                description_quality__gte=4, description_quality__lte=6
            )
        if value == "good":
            return queryset.filter(description_quality__gte=7)
        if value == "none":
            return queryset.filter(description_quality__isnull=True)
        return queryset


class LLMAdminMixin(admin.ModelAdmin):
    """Changelist actions + change-form buttons for LLM translate/assess.

    Mix into a concrete ModelAdmin (e.g. ``class HutsAdmin(LLMAdminMixin,
    ModelAdmin)``); subclasses django's ModelAdmin only for attribute/type
    resolution — behaviour comes from the concrete admin's MRO.
    """

    change_form_template = "translations/llm_change_form.html"

    # Changelist bulk actions — Django only collects actions listed here
    # (decorated methods are NOT auto-discovered).
    actions = ("translate_selected", "assess_selected")

    @display(
        description=_("Quality"),  # pyright: ignore[reportArgumentType]  # lazy-gettext idiom (i18n-safe)
        ordering="description_quality",
        label={
            str(score): "danger"
            if score <= 3
            else "warning"
            if score <= 6
            else "success"
            for score in range(1, 11)
        },
    )
    def description_quality_display(self, obj):
        if obj.description_quality is None:
            return "–"
        return str(obj.description_quality)

    # -- changelist actions ------------------------------------------------

    def get_actions(self, request) -> dict[str, t.Any]:
        """Hide the LLM bulk actions when the API is unconfigured."""
        if not translations_api_enabled():
            return {}
        return super().get_actions(request)

    @action(  # pyright: ignore[reportArgumentType]  # decorator kwargs
        description=_(  # pyright: ignore[reportArgumentType]  # lazy-gettext idiom (i18n-safe)
            "Translate missing languages (AI)"
        ),
        permissions=["change"],
    )
    def translate_selected(self, request: HttpRequest, queryset) -> None:
        self._run_llm(request, queryset, mode="translate")

    @action(  # pyright: ignore[reportArgumentType]  # decorator kwargs
        description=_(  # pyright: ignore[reportArgumentType]  # lazy-gettext idiom (i18n-safe)
            "Assess description (AI)"
        ),
        permissions=["change"],
    )
    def assess_selected(self, request: HttpRequest, queryset) -> None:
        self._run_llm(request, queryset, mode="assess")

    # -- change-form buttons -----------------------------------------------

    def get_urls(self):
        if not translations_api_enabled():
            return super().get_urls()
        info = (self.model._meta.app_label, self.model._meta.model_name)
        return [
            path(
                "llm/translate/<int:pk>/",
                self.admin_site.admin_view(self.llm_translate_view),
                name="%s_%s_llm_translate" % info,
            ),
            path(
                "llm/assess/<int:pk>/",
                self.admin_site.admin_view(self.llm_assess_view),
                name="%s_%s_llm_assess" % info,
            ),
        ] + super().get_urls()

    def llm_translate_view(self, request: HttpRequest, pk: int):
        return self._llm_view(request, pk, mode="translate")

    def llm_assess_view(self, request: HttpRequest, pk: int):
        return self._llm_view(request, pk, mode="assess")

    def _llm_view(self, request: HttpRequest, pk: int, mode: str):
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])
        if not self.has_change_permission(request):
            raise PermissionDenied
        obj = get_object_or_404(self.model, pk=pk)
        client = self._build_client(request)
        if client is not None:
            try:
                stats = self._call(obj, client, mode)
            except TranslationError as error:
                messages.error(request, f"{obj}: {error}")
            else:
                self._message_stats(request, obj, stats, mode)
        return self._redirect_to_change(obj)

    def render_change_form(
        self, request, context, add=False, change=False, form_url="", obj=None
    ):
        context = context or {}
        obj = context.get("original") or obj
        if translations_api_enabled() and obj is not None and obj.pk:
            info = (self.model._meta.app_label, self.model._meta.model_name)
            context["llm_translate_url"] = reverse(
                "admin:%s_%s_llm_translate" % info, args=[obj.pk]
            )
            context["llm_assess_url"] = reverse(
                "admin:%s_%s_llm_assess" % info, args=[obj.pk]
            )
        return super().render_change_form(
            request, context, add=add, change=change, form_url=form_url, obj=obj
        )

    # -- internals ----------------------------------------------------------

    def _build_client(self, request: HttpRequest) -> TranslationClient | None:
        try:
            return TranslationClient()
        except ImproperlyConfigured as error:
            messages.error(request, str(error))
            return None

    def _call(self, obj, client, mode: str) -> dict[str, t.Any]:
        if mode == "translate":
            return translate_instance(obj, client=client)
        return assess_instance(obj, client=client)

    def _run_llm(self, request: HttpRequest, queryset, mode: str) -> None:
        client = self._build_client(request)
        if client is None:
            return
        done: list[str] = []
        skipped: list[str] = []
        errors: list[str] = []
        for obj in queryset:
            try:
                stats = self._call(obj, client, mode)
            except TranslationError as error:
                errors.append(f"{obj}: {error}")
                continue
            skipped_reason = stats.get("skipped")
            if skipped_reason:
                skipped.append(f"{obj} ({skipped_reason})")
            elif mode == "translate" and not stats.get("translated"):
                skipped.append(str(obj))
            else:
                done.append(self._describe(obj, stats, mode))
        self._message_batch(request, mode, done, skipped, errors)

    def _describe(self, obj, stats: dict[str, t.Any], mode: str) -> str:
        if mode == "translate":
            fields = sum(len(v) for v in stats.get("translated", {}).values())
            return f"{obj}: {fields} field(s)"
        line = f"{obj}: {stats['score']}/10"
        if stats.get("rework"):
            line += " → rework"
        return line

    def _message_stats(
        self, request: HttpRequest, obj, stats: dict[str, t.Any], mode: str
    ) -> None:
        skipped_reason = stats.get("skipped")
        if skipped_reason:
            messages.info(request, f"{obj}: skipped ({skipped_reason})")
        else:
            messages.success(request, self._describe(obj, stats, mode))

    def _message_batch(
        self,
        request: HttpRequest,
        mode: str,
        done: list[str],
        skipped: list[str],
        errors: list[str],
    ) -> None:
        verb = _("translated") if mode == "translate" else _("assessed")
        if done:
            self.message_user(
                request,
                _("%(n)s object(s) %(verb)s: %(list)s")
                % {"n": len(done), "verb": verb, "list": _join_truncated(done)},
                messages.SUCCESS,
            )
        if skipped:
            self.message_user(
                request,
                _("Skipped %(n)s: %(list)s")
                % {"n": len(skipped), "list": _join_truncated(skipped)},
                messages.INFO,
            )
        if errors:
            self.message_user(
                request,
                _("Errors (%(n)s): %(list)s")
                % {"n": len(errors), "list": _join_truncated(errors)},
                messages.ERROR,
            )

    def _redirect_to_change(self, obj):
        info = (self.model._meta.app_label, self.model._meta.model_name)
        return redirect("admin:%s_%s_change" % info, obj.pk)


def _join_truncated(items: list[str]) -> str:
    head = ", ".join(items[:_MAX_LISTED])
    if len(items) > _MAX_LISTED:
        head += ", …"
    return head

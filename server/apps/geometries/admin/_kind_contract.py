"""Admin registration for the kind contract model.

``CategoryExtraSchema`` parity: seeded from the kinds registry by
migration, then admin-editable — classifier vocabularies and the
operations/seasonality gates evolve without a deploy. Changes take
effect on the next write (existing rows are not retro-checked).
"""

from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from unfold.decorators import display

from server.apps.manager.admin import ModelAdmin

from ..models import CategoryKindContract


@admin.register(CategoryKindContract)
class CategoryKindContractAdmin(ModelAdmin):
    """Kind contracts on contract-group categories."""

    list_display = (
        "category",
        "classifiers_display",
        "has_operations",
        "has_seasonality",
        "modified",
    )
    list_filter = ("has_operations", "has_seasonality")
    search_fields = ("category__slug", "category__identifier")
    autocomplete_fields = ("category",)
    filter_horizontal = ("allowed_classifiers",)

    @display(description=_("Allowed classifiers"))
    def classifiers_display(self, obj: CategoryKindContract) -> str:
        """Comma-separated vocabulary roots allowed under the group."""
        slugs = list(obj.allowed_classifiers.values_list("slug", flat=True))
        return ", ".join(slugs) if slugs else "—"

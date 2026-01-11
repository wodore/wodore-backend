import contextlib

from django.conf import settings
from django.contrib import admin
from django.db.models import Count
from django.db.models.functions import Lower
from django.http import HttpRequest
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

with contextlib.suppress(ModuleNotFoundError):
    from django_stubs_ext import QuerySetAny

from unfold.decorators import display

from server.apps.manager.admin import ModelAdmin
from server.apps.translations.forms import required_i18n_fields_form_factory

from .models import Category


class ParentCategoryFilter(admin.RelatedFieldListFilter):
    """Custom filter for parent categories that shows clean names without 'root.' prefix."""

    def field_choices(self, field, request, model_admin):
        """Override field_choices to show cleaner category names and sort NULL parents first."""
        # Get original choices from parent
        choices = super().field_choices(field, request, model_admin)
        # Clean up the display names and separate into two groups
        null_parent_choices = []
        with_parent_choices = []

        for pk, displ in choices:
            # Clean up the display name
            if displ and str(displ).startswith("root."):
                displ = str(displ)[5:]  # Remove 'root.' prefix

            # Separate NULL parents from non-NULL
            # Check if this is a root category by querying
            if pk is not None:
                category = Category.objects.filter(pk=pk, parent__isnull=True).exists()
                if category:
                    null_parent_choices.append((pk, displ))
                else:
                    with_parent_choices.append((pk, displ))

        # Return NULL parents first, then others
        return null_parent_choices + with_parent_choices


class ChildCategoryInline(admin.TabularInline):
    """Inline to show child categories in Category admin"""

    model = Category
    fk_name = "parent"
    tab = True  # Display as a tab in Unfold admin
    extra = 0
    fields = (
        "symbol_preview",
        "name_i18n",
        "slug",
        "order",
        "is_active",
        "view_link",
    )
    readonly_fields = (
        "symbol_preview",
        "name_i18n",
        "view_link",
        "slug",
    )
    can_delete = False  # Prevent deletion from inline
    verbose_name = _("Child Category")
    verbose_name_plural = _("Child Categories")

    def get_queryset(self, request: HttpRequest):
        """Optimize queryset for inline display."""
        qs = super().get_queryset(request)
        return qs.order_by("order", "slug")

    @display(description="")
    def symbol_preview(self, obj):
        """Display symbol preview."""
        if obj.symbol_detailed:
            return mark_safe(
                f'<img src="{obj.symbol_detailed.url}" alt="{obj.slug}" style="width: 24px; height: 24px;" />'
            )
        elif obj.symbol_simple:
            return mark_safe(
                f'<img src="{obj.symbol_simple.url}" alt="{obj.slug}" style="width: 24px; height: 24px;" />'
            )
        return "-"

    @display(description=_("View"))
    def view_link(self, obj):
        """Link to view/edit this child category."""
        if obj.pk:
            url = reverse("admin:categories_category_change", args=[obj.pk])
            return format_html('<a href="{}">Edit</a>', url)
        return "-"


@admin.register(Category)
class CategoryAdmin(ModelAdmin):
    form = required_i18n_fields_form_factory("name")

    search_fields = ("name", "slug", "identifier")
    list_display = (
        "title",
        "symbol_img",
        "icon_img",
        # "order_display",
        "identifier_display",
        "slug",
        "children_count",
        # "parent_display",
        "order",
        "is_active",
        "parent",
    )

    list_filter = (
        "is_active",
        ("parent", ParentCategoryFilter),
    )

    list_editable = ("order", "parent")
    list_per_page = 20  # Limit rows per page for better performance
    ordering = ("-parent", "order")  # Order by parent (NULL first, then by parent ID)
    search_fields = ("name", "slug")

    readonly_fields = ("identifier", "name_i18n", "description_i18n")

    fieldsets = (
        (
            _("Main Information"),
            {
                "fields": (
                    ("slug", "identifier", "is_active"),
                    "name_i18n",
                    ("parent", "default", "order"),
                    "description_i18n",
                )
            },
        ),
        (
            _("Translations"),
            {
                "classes": ["collapse"],
                "fields": [
                    tuple([f"name_{code}" for code in settings.LANGUAGE_CODES]),
                ]
                + [f"description_{code}" for code in settings.LANGUAGE_CODES],
            },
        ),
        (
            _("Symbols"),
            {"fields": (("symbol_detailed", "symbol_simple", "symbol_mono"),)},
        ),
    )

    inlines = (ChildCategoryInline,)

    def get_queryset(self, request: HttpRequest) -> "QuerySetAny":
        """Optimize queryset with parent selection and annotate children count."""
        qs = super().get_queryset(request)
        # Use select_related for parent and default to avoid N+1 queries
        # Annotate children count efficiently in a single query
        return qs.select_related("parent", "default").annotate(
            children_count_annotated=Count("children")
        )

    @display(
        header=True, description=_("Name and Description"), ordering=Lower("name_i18n")
    )
    def title(self, obj):
        """Display name, description, and small symbol."""
        # level_indent = "　" * obj.get_level()  # Japanese space for indentation
        level_indent = ""
        name = f"{level_indent}{obj.name_i18n}" if obj.name_i18n else obj.slug
        description = (
            f"{level_indent}{obj.description_i18n}" if obj.description_i18n else ""
        )
        avatar = self.avatar(obj.symbol_simple.url) if obj.symbol_simple else ""
        return (name, description, avatar)

    @display(description=_("Symbol"))
    def symbol_img(self, obj):
        """Display detailed symbol."""
        if obj.symbol_detailed:
            return mark_safe(
                f'<img src="{obj.symbol_detailed.url}" width="34" alt="symbol"/>'
            )
        return "-"

    @display(description=_("Mono"))
    def icon_img(self, obj):
        """Display monochrome symbol."""
        if obj.symbol_mono:
            return mark_safe(
                f'<img src="{obj.symbol_mono.url}" width="16" alt="mono"/>'
            )
        return "-"

    @display(description=_("Identifier"), ordering="identifier")
    def identifier_display(self, obj):
        """Display identifier without 'root.' prefix."""
        identifier = obj.identifier
        if identifier and identifier.startswith("root."):
            return identifier[5:]  # Remove 'root.' prefix
        return identifier

    @display(description=_("Children"), label=True)
    def children_count(self, obj):
        """Display count of children using annotated field to avoid N+1 queries."""
        # Use the annotated count from get_queryset
        count = getattr(obj, "children_count_annotated", 0)
        if count > 0:
            url = reverse("admin:categories_category_changelist")
            filter_param = f"?parent__id__exact={obj.id}"
            return format_html(
                '<a href="{}{}" style="font-size: 14px;">{}</a>',
                url,
                filter_param,
                count,
            )
        return "-"

    @display(description=_("Order"), ordering="order")
    def order_display(self, obj):
        """Display order value."""
        return mark_safe(f"<small>{obj.order}</small>")

    @display(description=_("Parent"), label=True, ordering="parent")
    def parent_display(self, obj):
        """Display parent category if exists."""
        if obj.parent:
            return obj.parent.name_i18n or obj.parent.slug
        return format_html('<span style="color: #999;">Root</span>')

    def avatar(self, url):
        """Helper to create small avatar image."""
        return mark_safe(f'<img src="{url}" width="20" alt="avatar"/>')

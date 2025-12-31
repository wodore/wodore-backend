import datetime

from django.conf import settings
from django.contrib import admin
from django.contrib.admin import SimpleListFilter
from django.db.models import QuerySet
from django.db.models.functions import Lower
from django.http import HttpRequest
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

from unfold.decorators import display

from server.apps.manager.admin import ModelAdmin

from .models import AvailabilityStatus, HutAvailability, HutAvailabilityHistory


class AvailabilityDateFilter(SimpleListFilter):
    """Custom filter for availability date ranges"""

    title = _("availability date range")
    parameter_name = "date_range"

    def lookups(self, request, model_admin):
        return (
            ("1day", _("Next 1 day")),
            ("7days", _("Next 7 days")),
            ("1month", _("Next 1 month")),
            ("all", _("All dates")),
        )

    def queryset(self, request, queryset):
        today = timezone.now().date()
        if self.value() == "1day":
            return queryset.filter(
                availability_date__gte=today,
                availability_date__lte=today + datetime.timedelta(days=1),
            )
        elif self.value() == "7days":
            return queryset.filter(
                availability_date__gte=today,
                availability_date__lte=today + datetime.timedelta(days=7),
            )
        elif self.value() == "1month":
            return queryset.filter(
                availability_date__gte=today,
                availability_date__lte=today + datetime.timedelta(days=30),
            )
        elif self.value() == "all":
            return queryset
        # Default: next 7 days
        return queryset.filter(
            availability_date__gte=today,
            availability_date__lte=today + datetime.timedelta(days=7),
        )


def get_occupancy_icon_html(occupancy_status: str, show_text: bool = True) -> str:
    """Get HTML for occupancy icon with optional text label"""
    icon_map = {
        "empty": "occupation_empty.svg",
        "low": "occupation_low.svg",
        "medium": "occupation_medium.svg",
        "high": "occupation_high.svg",
        "full": "occupation_full.svg",
        "unknown": "occupation_unknown.svg",
    }

    icon_file = icon_map.get(occupancy_status, "occupation_unknown.svg")
    icon_url = f"{settings.STATIC_URL}huts/occupation/source/{icon_file}"

    if show_text:
        return format_html(
            '<div style="display: flex; align-items: center; gap: 6px;">'
            '<img src="{}" alt="{}" style="width: 24px; height: 24px;" />'
            #'<span style="font-size: 10px; padding: 1px 4px; background: rgba(0,0,0,0.05); border-radius: 3px; color: #4b5563; font-weight: 500;">{}</span>'
            "</div>",
            icon_url,
            occupancy_status,
        )
    else:
        return format_html(
            '<img src="{}" alt="{}" style="width: 20px; height: 20px;" />',
            icon_url,
            occupancy_status,
        )


def get_occupancy_progress_bar(occupancy_percent: float) -> str:
    """Get HTML for occupancy progress bar matching SVG icon colors"""
    # Colors from occupation SVG icons
    if occupancy_percent >= 75:
        color = "#d32f2f"  # full - red
    elif occupancy_percent >= 50:
        color = "#ffa726"  # high - orange
    elif occupancy_percent >= 25:
        color = "#99cc33"  # medium - yellow-green
    else:
        color = "#33ff33"  # low/empty - green

    percent_text = f"{occupancy_percent:.0f}%"

    return format_html(
        '<div style="display: flex; align-items: center; gap: 8px; min-width: 120px; padding: 2px 0;">'
        '<div style="flex: 1; background: rgba(0,0,0,0.08); border-radius: 3px; height: 10px; overflow: hidden;">'
        '<div style="background: {}; height: 100%; width: {}%;"></div>'
        "</div>"
        '<span style="font-size: 11px; font-weight: 500; min-width: 35px; text-align: right; color: #4b5563;">{}</span>'
        "</div>",
        color,
        occupancy_percent,
        percent_text,
    )


class HutAvailabilityHistoryInline(admin.TabularInline):
    model = HutAvailabilityHistory
    extra = 0
    fields = (
        "free",
        "total",
        "occupancy_percent",
        "occupancy_status",
        "hut_type",
        "first_checked",
        "last_checked",
        # "duration_display",
    )
    readonly_fields = (
        "free",
        "total",
        "occupancy_percent",
        "occupancy_status",
        "hut_type",
        "first_checked",
        "last_checked",
        "duration_display",
    )
    can_delete = False

    @display(description=_("Duration"))
    def duration_display(self, obj):
        if obj.pk:
            seconds = obj.duration_seconds
            if seconds < 3600:
                return f"{seconds / 60:.1f} min"
            elif seconds < 86400:
                return f"{seconds / 3600:.1f} hours"
            else:
                return f"{seconds / 86400:.1f} days"
        return "-"


@admin.register(AvailabilityStatus)
class AvailabilityStatusAdmin(ModelAdmin):
    """Admin for Availability Status tracking"""

    list_display = (
        "hut_header",
        "has_data_display",
        "consecutive_failures_display",
        "failing_since",
        "last_checked",
        "last_success",
    )
    list_display_links = ("hut_header",)
    list_filter = (
        "has_data",
        "consecutive_failures",
    )
    search_fields = ("hut__name", "hut__slug")
    readonly_fields = (
        "hut",
        "last_checked",
        "last_success",
        "has_data",
        "consecutive_failures",
        "failing_since",
        "created",
        "modified",
    )
    list_per_page = 100

    fieldsets = (
        (
            _("Hut"),
            {"fields": ("hut",)},
        ),
        (
            _("Status"),
            {
                "fields": (
                    "has_data",
                    "consecutive_failures",
                    "failing_since",
                )
            },
        ),
        (
            _("Timestamps"),
            {
                "fields": (
                    "last_checked",
                    "last_success",
                    "created",
                    "modified",
                )
            },
        ),
    )

    def get_queryset(self, request: HttpRequest) -> QuerySet:
        """Optimize queryset with select_related"""
        qs = super().get_queryset(request)
        return qs.select_related("hut")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    @display(header=True, description=_("Hut"), ordering=Lower("hut__name"))
    def hut_header(self, obj):
        """Display hut name and slug as header with link"""
        return (obj.hut.name, obj.hut.slug)

    @display(description=_("Has Data"), ordering="has_data", boolean=True)
    def has_data_display(self, obj):
        """Display has_data field with custom label"""
        return obj.has_data

    @display(description=_("Failures"), ordering="consecutive_failures")
    def consecutive_failures_display(self, obj):
        """Display consecutive_failures field with custom label"""
        return obj.consecutive_failures

    @display(description=_("Failing Since"))
    def failing_since(self, obj):
        """Calculate and display when the hut started failing (if currently failing)"""
        if obj.consecutive_failures == 0:
            return "-"
        elif not obj.last_success:
            return _("always")
        return obj.last_success


class HutAvailabilityViewInline(admin.TabularInline):
    """Inline to show availability data in Hut admin"""

    model = HutAvailability
    tab = True  # Display as a tab in Unfold admin
    extra = 0
    max_num = 30  # Limit display to avoid overwhelming the page
    fields = (
        "status_icon",
        "availability_date",
        "places_display",
        "occupancy_progress",
        "hut_type_icon",
        "reservation_status",
        "last_checked",
        "view_link",
    )
    readonly_fields = (
        "status_icon",
        "availability_date",
        "places_display",
        "occupancy_progress",
        "hut_type_icon",
        "reservation_status",
        "last_checked",
        "view_link",
    )
    can_delete = False
    verbose_name = _("Availability")
    verbose_name_plural = _("Availability (Next 14 Days)")

    def get_queryset(self, request: HttpRequest) -> QuerySet:
        """Show only next 14 days of availability"""
        from django.utils import timezone
        import datetime

        qs = super().get_queryset(request)
        today = timezone.now().date()
        end_date = today + datetime.timedelta(days=14)
        # Filter for next 14 days only
        return (
            qs.filter(availability_date__gte=today, availability_date__lte=end_date)
            .select_related("hut_type")
            .order_by("availability_date")
        )

    def has_add_permission(self, request: HttpRequest, obj=None) -> bool:
        return False

    @display(description=_("Places"))
    def places_display(self, obj):
        return f"{obj.free}/{obj.total}"

    @display(description=_("Occupancy"), label=True)
    def occupancy_progress(self, obj):
        return mark_safe(get_occupancy_progress_bar(obj.occupancy_percent))

    @display(description="")
    def status_icon(self, obj):
        return mark_safe(get_occupancy_icon_html(obj.occupancy_status, show_text=True))

    @display(description=_("Type"))
    def hut_type_icon(self, obj):
        if obj.hut_type and obj.hut_type.symbol_simple:
            return mark_safe(
                f'<img src="{obj.hut_type.symbol_simple.url}" alt="{obj.hut_type.name}" style="width: 20px; height: 20px;" />'
            )
        return "-"

    @display(description=_("View"))
    def view_link(self, obj):
        if obj.pk:
            url = reverse("admin:availability_hutavailability_change", args=[obj.pk])
            return format_html('<a href="{}">View</a>', url)
        return "-"


@admin.register(HutAvailability)
class HutAvailabilityAdmin(ModelAdmin):
    list_display = (
        "status_icon",
        "hut_header",
        "availability_date",
        "places_display",
        "occupancy_progress",
        "hut_type_icon",
        "reservation_status_label",
        "source_display",
        "last_checked",
    )
    list_display_links = ("hut_header",)
    list_filter = (
        AvailabilityDateFilter,
        "occupancy_status",
        "reservation_status",
        "hut_type",
        "source_organization",
    )
    search_fields = ("hut__name", "hut__slug")
    readonly_fields = (
        "hut",
        "source_organization",
        "source_id",
        "availability_date",
        "free",
        "total",
        "occupancy_percent",
        "occupancy_steps",
        "occupancy_status",
        "reservation_status",
        "link",
        "hut_type",
        "first_checked",
        "last_checked",
        "created",
        "modified",
    )
    date_hierarchy = "availability_date"
    list_per_page = 100

    fieldsets = (
        (
            _("Hut Information"),
            {
                "fields": (
                    ("hut", "source_organization", "source_id"),
                    (
                        "availability_date",
                        "occupancy_status",
                        "reservation_status",
                        "hut_type",
                    ),
                    ("free", "total", "occupancy_percent", "occupancy_steps"),
                    "link",
                )
            },
        ),
        (
            _("Timestamps"),
            {"fields": (("first_checked", "last_checked"), ("created", "modified"))},
        ),
    )

    inlines = (HutAvailabilityHistoryInline,)

    def get_queryset(self, request: HttpRequest) -> QuerySet:
        """Optimize queryset with select_related"""
        qs = super().get_queryset(request)
        return qs.select_related("hut", "source_organization", "hut_type")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    @display(description=_("Places"))
    def places_display(self, obj):
        return f"{obj.free}/{obj.total}"

    @display(description=_("Occupancy"), label=True)
    def occupancy_progress(self, obj):
        return mark_safe(get_occupancy_progress_bar(obj.occupancy_percent))

    @display(description="")
    def status_icon(self, obj):
        return mark_safe(get_occupancy_icon_html(obj.occupancy_status, show_text=True))

    @display(header=True, description=_("Hut"), ordering=Lower("hut__name"))
    def hut_header(self, obj):
        """Display hut name and slug as header with link"""
        return (obj.hut.name, obj.hut.slug)

    @display(description=_("Type"))
    def hut_type_icon(self, obj):
        if obj.hut_type and obj.hut_type.symbol_simple:
            return mark_safe(
                f'<img src="{obj.hut_type.symbol_simple.url}" alt="{obj.hut_type.name}" style="width: 20px; height: 20px;" />'
            )
        return "-"

    @display(description=_("Reservation"), label=True)
    def reservation_status_label(self, obj):
        """Display reservation status as a styled label"""
        return obj.reservation_status

    @display(description=_("Source"))
    def source_display(self, obj):
        """Display source organization with logo"""
        if obj.source_organization and obj.source_organization.logo:
            return mark_safe(
                f'<div style="display: flex; align-items: center; gap: 6px;">'
                f'<img src="{settings.MEDIA_URL}{obj.source_organization.logo}" alt="{obj.source_organization.name}" style="width: 20px; height: 20px;" />'
                f'<span style="font-size: 10px;">{obj.source_id}</span>'
                f"</div>"
            )
        return obj.source_id if obj.source_id else "-"


@admin.register(HutAvailabilityHistory)
class HutAvailabilityHistoryAdmin(ModelAdmin):
    list_display = (
        "status_icon",
        "hut_header",
        "availability_date",
        "places_display",
        "occupancy_progress",
        "hut_type_icon",
        "first_checked",
        "last_checked",
        "duration_display",
    )
    list_filter = (
        "occupancy_status",
        "hut_type",
        "availability_date",
    )
    search_fields = ("hut__name", "hut__slug")
    readonly_fields = (
        "availability",
        "hut",
        "availability_date",
        "free",
        "total",
        "occupancy_percent",
        "occupancy_status",
        "hut_type",
        "first_checked",
        "last_checked",
        "duration_display",
        "created",
        "modified",
    )
    date_hierarchy = "availability_date"
    list_per_page = 100

    fieldsets = (
        (
            _("Reference"),
            {
                "fields": (
                    "availability",
                    "hut",
                    "availability_date",
                )
            },
        ),
        (
            _("Snapshot Data"),
            {
                "fields": (
                    "free",
                    "total",
                    "occupancy_percent",
                    "occupancy_status",
                    "hut_type",
                )
            },
        ),
        (
            _("Timestamps"),
            {
                "fields": (
                    "first_checked",
                    "last_checked",
                    # "duration_display",
                    "created",
                    "modified",
                )
            },
        ),
    )

    def get_queryset(self, request: HttpRequest) -> QuerySet:
        """Optimize queryset with select_related"""
        qs = super().get_queryset(request)
        return qs.select_related("hut", "availability", "hut_type")

    @display(header=True, description=_("Hut"), ordering=Lower("hut__name"))
    def hut_header(self, obj):
        """Display hut name and slug as header with link"""
        return (obj.hut.name, obj.hut.slug)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    @display(description=_("Places"))
    def places_display(self, obj):
        return f"{obj.free}/{obj.total}"

    @display(description=_("Occupancy"), label=True)
    def occupancy_progress(self, obj):
        return mark_safe(get_occupancy_progress_bar(obj.occupancy_percent))

    @display(description="")
    def status_icon(self, obj):
        return mark_safe(get_occupancy_icon_html(obj.occupancy_status, show_text=True))

    @display(description=_("Type"))
    def hut_type_icon(self, obj):
        if obj.hut_type and obj.hut_type.symbol_simple:
            return mark_safe(
                f'<img src="{obj.hut_type.symbol_simple.url}" alt="{obj.hut_type.name}" style="width: 20px; height: 20px;" />'
            )
        return "-"

    @display(description=_("Duration"))
    def duration_display(self, obj):
        if obj.pk:
            seconds = obj.duration_seconds
            if seconds < 3600:
                return f"{seconds / 60:.1f} min"
            elif seconds < 86400:
                return f"{seconds / 3600:.1f} hours"
            else:
                return f"{seconds / 86400:.1f} days"
        return "-"

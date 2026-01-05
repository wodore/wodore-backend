"""
API endpoints for hut availability data.

Provides optimized GeoJSON endpoints using PostgreSQL's native GeoJSON generation
for improved performance compared to Python-based serialization.
"""

import datetime

import msgspec
from ninja import Field, Path, Query, Schema
from ninja.decorators import decorate_view
from ninja.errors import HttpError

from django.contrib.postgres.aggregates import JSONBAgg
from django.db.models import F, Max, Value
from django.db.models.functions import Coalesce, JSONObject
from django.http import HttpRequest, HttpResponse
from django.views.decorators.cache import cache_control

from server.apps.translations import LanguageParam, activate, with_language_param

from .models import HutAvailability, HutAvailabilityHistory
from .schemas import (
    AvailabilityTrendSchema,
    CurrentAvailabilitySchema,
    HutAvailabilityFeatureCollection,
)
from .utils import parse_availability_date


# Path schemas
class DatePathParam(Schema):
    """Path parameter for date."""

    date: str = Field(
        ...,
        description="Start date. Accepts ISO dates (2026-01-15, 26-01-15), European format (15.01.2026), or keywords: 'now', 'today', 'weekend'.",
    )


class DatePathParamTrend(Schema):
    """Path parameter for trend endpoint."""

    date: str = Field(
        ...,
        description="Target date to analyze. Accepts ISO dates (2026-01-15, 26-01-15), European format (15.01.2026), or keywords: 'now', 'today', 'weekend'.",
    )


# Query schemas
class AvailabilityGeoJSONQuery(Schema):
    """Query parameters for GeoJSON availability endpoint."""

    slugs: str | None = Field(
        None,
        title="Hut Slugs",
        description="Comma-separated list of hut slugs to filter (e.g., 'aarbiwak,almageller'). If not set, returns all huts.",
    )
    days: int = Field(
        1,
        description="Number of days to fetch from start date.",
        ge=1,
        le=365,
    )
    offset: int = Field(
        0,
        description="Pagination offset for results.",
        ge=0,
    )
    limit: int | None = Field(
        None,
        description="Maximum number of huts to return. If not set, returns all matching huts.",
        ge=1,
    )


class CurrentAvailabilityQuery(Schema):
    """Query parameters for current availability endpoint."""

    days: int = Field(
        1,
        description="Number of days to fetch from start date.",
        ge=1,
        le=365,
    )


class AvailabilityTrendQuery(Schema):
    """Query parameters for availability trend endpoint."""

    limit: int = Field(
        7,
        description="How many days back to show history from the target date.",
        ge=1,
        le=365,
    )


# Import huts router to register endpoints there
# Import at function level to avoid circular imports
def _get_huts_router():
    from server.apps.huts.api._router import router

    return router


@_get_huts_router().get(
    "availability/{date}.geojson",
    operation_id="get_hut_availability_geojson",
    response=HutAvailabilityFeatureCollection,
)
@with_language_param("lang")
@decorate_view(cache_control(max_age=600))  # Cache for 10 minutes
def get_hut_availability_geojson(
    request: HttpRequest,
    response: HttpResponse,
    path: Path[DatePathParam],
    lang: LanguageParam,
    queries: Query[AvailabilityGeoJSONQuery],
) -> HttpResponse:
    """Get availability data as GeoJSON FeatureCollection for map visualization."""
    activate(lang)

    # Parse date parameter
    start_datetime = parse_availability_date(path.date)
    start_date = start_datetime.date()

    # Build base queryset - group by hut to get all dates for each hut
    qs = HutAvailability.objects.filter(
        availability_date__gte=start_date,
        availability_date__lt=start_date + datetime.timedelta(days=queries.days),
        hut__is_active=True,
        hut__is_public=True,
    ).select_related("hut", "source_organization", "hut_type")

    # Apply slug filter if provided
    if queries.slugs:
        hut_slugs_list = [s.strip().lower() for s in queries.slugs.split(",")]
        qs = qs.filter(hut__slug__in=hut_slugs_list)

    # Group availability records by hut and aggregate data
    # Use Max() to extract scalar values from grouped rows (all values are identical per hut)
    qs = qs.values("hut_id").annotate(
        # Hut properties - use Max() for scalar fields in GROUP BY
        slug=Max(F("hut__slug")),
        id=F("hut_id"),  # Expose hut_id as 'id' to match schema
        source_id=Max(F("source_id")),
        source=Max(F("source_organization__slug")),
        location=F(
            "hut__location"
        ),  # No Max() needed - geometry is same for all records
        # Metadata
        days=Value(queries.days),
        start_date=Value(start_date.isoformat()),
        # Aggregate availability data as JSON array
        data=JSONBAgg(
            JSONObject(
                date=F("availability_date"),
                reservation_status=F("reservation_status"),
                free=F("free"),
                total=F("total"),
                occupancy_percent=F("occupancy_percent"),
                occupancy_steps=F("occupancy_steps"),
                occupancy_status=F("occupancy_status"),
                hut_type=Coalesce(F("hut_type__slug"), Value("unknown")),
            ),
            ordering="availability_date",  # Ensure data is ordered by date
        ),
    )

    # Apply pagination
    if queries.limit is not None:
        qs = qs[queries.offset : queries.offset + queries.limit]
    elif queries.offset > 0:
        qs = qs[queries.offset :]

    # Build GeoJSON properties - field names match schema exactly (no post-processing needed)
    properties = [
        "slug",
        "id",
        "source_id",
        "source",
        "days",
        "start_date",
        "data",
    ]

    # Import GeoJSON locally to avoid circular imports
    from server.apps.huts.api.expressions import GeoJSON

    # Generate GeoJSON using PostgreSQL
    # simplify=False because point geometries don't need simplification
    geojson = qs.aggregate(
        GeoJSON(
            geom_field="location",
            fields=properties,
            decimals=5,
            simplify=False,  # No need to simplify point geometries
        ),
    )["geojson"]

    # Write response directly - no Python post-processing needed
    response.write(msgspec.json.encode(geojson))
    return response


@_get_huts_router().get(
    "{slug}/availability/{date}",
    operation_id="get_hut_availability_current",
    response=CurrentAvailabilitySchema,
)
@with_language_param("lang")
@decorate_view(cache_control(max_age=300))  # Cache for 5 minutes
def get_hut_availability_current(
    request: HttpRequest,
    slug: str,
    path: Path[DatePathParam],
    lang: LanguageParam,
    queries: Query[CurrentAvailabilityQuery],
) -> CurrentAvailabilitySchema:
    """Get current availability data for a specific hut with detailed metadata and booking links."""
    from server.apps.huts.models import Hut

    activate(lang)

    # Get the hut
    try:
        hut = Hut.objects.get(slug=slug, is_active=True, is_public=True)
    except Hut.DoesNotExist:
        raise HttpError(404, f"Hut with slug '{slug}' not found")

    # Parse date parameter
    start_datetime = parse_availability_date(path.date)
    start_date = start_datetime.date()

    # Query availability data
    availabilities = (
        HutAvailability.objects.filter(
            hut=hut,
            availability_date__gte=start_date,
            availability_date__lt=start_date + datetime.timedelta(days=queries.days),
        )
        .select_related("source_organization", "hut_type")
        .order_by("availability_date")
    )

    if not availabilities:
        raise HttpError(404, f"No availability data found for hut '{slug}'")

    # Get source info from first availability record
    first_avail = availabilities[0]

    # Get the external link to the source hut page from the HutOrganizationAssociation
    from server.apps.huts.models import HutOrganizationAssociation

    hut_org_association = HutOrganizationAssociation.objects.filter(
        hut=hut,
        organization=first_avail.source_organization,
        source_id=first_avail.source_id,
    ).first()

    source_link = hut_org_association.link if hut_org_association else ""

    # Build response
    data = [
        {
            "date": avail.availability_date,
            "reservation_status": avail.reservation_status,
            "free": avail.free,
            "total": avail.total,
            "occupancy_percent": avail.occupancy_percent,
            "occupancy_steps": avail.occupancy_steps,
            "occupancy_status": avail.occupancy_status,
            "hut_type": avail.hut_type.slug if avail.hut_type else "unknown",
            "link": avail.link,
            "first_checked": avail.first_checked,
            "last_checked": avail.last_checked,
        }
        for avail in availabilities
    ]

    return CurrentAvailabilitySchema(
        slug=hut.slug,
        id=hut.id,
        source_id=first_avail.source_id,
        source=first_avail.source_organization.slug,
        source_link=source_link,
        days=queries.days,
        start_date=start_date,
        data=data,
    )


@_get_huts_router().get(
    "{slug}/availability/{date}/trend",
    operation_id="get_hut_availability_trend",
    response=AvailabilityTrendSchema,
)
@with_language_param("lang")
@decorate_view(cache_control(max_age=600))  # Cache for 10 minutes
def get_hut_availability_trend(
    request: HttpRequest,
    slug: str,
    path: Path[DatePathParamTrend],
    lang: LanguageParam,
    queries: Query[AvailabilityTrendQuery],
) -> AvailabilityTrendSchema:
    """Get historical availability trend data showing how availability changed over time for a specific date."""
    from server.apps.huts.models import Hut

    activate(lang)

    # Get the hut
    try:
        hut = Hut.objects.get(slug=slug, is_active=True, is_public=True)
    except Hut.DoesNotExist:
        raise HttpError(404, f"Hut with slug '{slug}' not found")

    # Parse target date
    target_datetime = parse_availability_date(path.date)
    target_date = target_datetime.date()

    # Calculate period (use datetime objects for timezone-aware comparisons)
    period_start = target_datetime - datetime.timedelta(days=queries.limit)
    period_end = target_datetime

    # Query history data
    # Get all history records for this hut/date where the record was observed during our period
    history = (
        HutAvailabilityHistory.objects.filter(
            hut=hut,
            availability_date=target_date,
            first_checked__gte=period_start,
            first_checked__lte=period_end,
        )
        .select_related("hut_type")
        .order_by("-first_checked")
    )  # Newest first

    if not history:
        raise HttpError(
            404,
            f"No historical data found for hut '{slug}' on date {target_date} within the specified period",
        )

    # Build response
    data = [
        {
            "date": h.availability_date,
            "free": h.free,
            "total": h.total,
            "occupancy_percent": h.occupancy_percent,
            "occupancy_status": h.occupancy_status,
            "reservation_status": h.reservation_status,
            "hut_type": h.hut_type.slug if h.hut_type else "unknown",
            "first_checked": h.first_checked,
            "last_checked": h.last_checked,
        }
        for h in history
    ]

    return AvailabilityTrendSchema(
        slug=hut.slug,
        id=hut.id,
        target_date=target_date,
        period_start=period_start,
        period_end=period_end,
        data=data,
    )

"""
API endpoints for hut availability data.

Provides optimized GeoJSON endpoints using PostgreSQL's native GeoJSON generation
for improved performance compared to Python-based serialization.
"""

import datetime

import msgspec
from ninja.decorators import decorate_view

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


# Import huts router to register endpoints there
# Import at function level to avoid circular imports
def _get_huts_router():
    from server.apps.huts.api._router import router

    return router


@_get_huts_router().get(
    "availability.geojson",
    operation_id="get_hut_availability_geojson",
    response=HutAvailabilityFeatureCollection,
)
@with_language_param("lang")
@decorate_view(cache_control(max_age=600))  # Cache for 10 minutes
def get_hut_availability_geojson(
    request: HttpRequest,
    response: HttpResponse,
    lang: LanguageParam,
    slugs: str | None = None,
    days: int = 1,
    date: str = "now",
    offset: int = 0,
    limit: int | None = None,
) -> HttpResponse:
    """
    Get availability data as GeoJSON FeatureCollection using PostgreSQL's native GeoJSON generation.

    Returns a GeoJSON FeatureCollection where each feature represents a hut with its availability
    data for the specified date range.
    """
    activate(lang)

    # Parse date parameter
    start_datetime = parse_availability_date(date)
    start_date = start_datetime.date()

    # Build base queryset - group by hut to get all dates for each hut
    qs = HutAvailability.objects.filter(
        availability_date__gte=start_date,
        availability_date__lt=start_date + datetime.timedelta(days=days),
        hut__is_active=True,
        hut__is_public=True,
    ).select_related("hut", "source_organization", "hut_type")

    # Apply slug filter if provided
    if slugs:
        hut_slugs_list = [s.strip().lower() for s in slugs.split(",")]
        qs = qs.filter(hut__slug__in=hut_slugs_list)

    # Group availability records by hut and aggregate data
    # Use Max() to extract scalar values from grouped rows (all values are identical per hut)
    qs = qs.values("hut_id").annotate(
        # Hut properties - use Max() for scalar fields in GROUP BY
        slug=Max(F("hut__slug")),
        id=F("hut_id"),  # Expose hut_id as 'id' to match schema
        source_id=Max(F("source_id")),
        source=Max(F("source_organization__slug")),
        location=Max(F("hut__location")),
        # Metadata
        days=Value(days),
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
    if limit is not None:
        qs = qs[offset : offset + limit]
    elif offset > 0:
        qs = qs[offset:]

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
    "{slug}/availability/current",
    operation_id="get_hut_availability_current",
    response=CurrentAvailabilitySchema,
)
@with_language_param("lang")
@decorate_view(cache_control(max_age=300))  # Cache for 5 minutes
def get_hut_availability_current(
    request: HttpRequest,
    slug: str,
    lang: LanguageParam,
    days: int = 1,
    date: str = "now",
) -> CurrentAvailabilitySchema:
    """
    Get current availability data for a specific hut with detailed metadata.

    Includes booking links and tracking timestamps for each day.
    """
    from server.apps.huts.models import Hut
    from ninja.errors import HttpError

    activate(lang)

    # Get the hut
    try:
        hut = Hut.objects.get(slug=slug, is_active=True, is_public=True)
    except Hut.DoesNotExist:
        raise HttpError(404, f"Hut with slug '{slug}' not found")

    # Parse date parameter
    start_datetime = parse_availability_date(date)
    start_date = start_datetime.date()

    # Query availability data
    availabilities = (
        HutAvailability.objects.filter(
            hut=hut,
            availability_date__gte=start_date,
            availability_date__lt=start_date + datetime.timedelta(days=days),
        )
        .select_related("source_organization", "hut_type")
        .order_by("availability_date")
    )

    if not availabilities:
        raise HttpError(404, f"No availability data found for hut '{slug}'")

    # Get source info from first availability record
    first_avail = availabilities[0]

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
        days=days,
        start_date=start_date,
        data=data,
    )


@_get_huts_router().get(
    "{slug}/availability/trend",
    operation_id="get_hut_availability_trend",
    response=AvailabilityTrendSchema,
)
@with_language_param("lang")
@decorate_view(cache_control(max_age=600))  # Cache for 10 minutes
def get_hut_availability_trend(
    request: HttpRequest,
    slug: str,
    lang: LanguageParam,
    date: str = "now",
    limit: int = 7,
) -> AvailabilityTrendSchema:
    """
    Get historical availability trend data for a specific hut and date.

    Shows how availability has changed over time for a specific target date,
    going back 'limit' days from the target date.
    """
    from server.apps.huts.models import Hut
    from ninja.errors import HttpError

    activate(lang)

    # Get the hut
    try:
        hut = Hut.objects.get(slug=slug, is_active=True, is_public=True)
    except Hut.DoesNotExist:
        raise HttpError(404, f"Hut with slug '{slug}' not found")

    # Parse target date
    target_datetime = parse_availability_date(date)
    target_date = target_datetime.date()

    # Calculate period
    period_start = target_date - datetime.timedelta(days=limit)
    period_end = target_date

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

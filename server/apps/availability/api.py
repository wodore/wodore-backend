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

from .models import HutAvailability
from .utils import parse_availability_date


# Import huts router to register endpoints there
# Import at function level to avoid circular imports
def _get_huts_router():
    from server.apps.huts.api._router import router

    return router


@_get_huts_router().get("availability.geojson", operation_id="get_availability_geojson")
@with_language_param("lang")
@decorate_view(cache_control(max_age=600))  # Cache for 10 minutes
def get_availability_geojson(
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
    Get availability data as GeoJSON using PostgreSQL's native GeoJSON generation.
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

    # Group availability records by hut and aggregate bookings
    # Use Max() to extract scalar values from grouped rows (all values are identical per hut)
    qs = qs.values("hut_id").annotate(
        # Hut properties - use Max() for scalar fields in GROUP BY
        slug=Max(F("hut__slug")),
        source_id=Max(F("source_id")),
        source=Max(F("source_organization__slug")),
        location=Max(F("hut__location")),
        # Metadata
        days=Value(days),
        start_date=Value(start_date.isoformat()),
        # Aggregate bookings as JSON array
        bookings=JSONBAgg(
            JSONObject(
                link=F("link"),
                date=F("availability_date"),
                reservation_status=F("reservation_status"),
                free=F("free"),
                total=F("total"),
                occupancy_percent=F("occupancy_percent"),
                occupancy_steps=F("occupancy_steps"),
                occupancy_status=F("occupancy_status"),
                hut_type=Coalesce(F("hut_type__slug"), Value("unknown")),
            )
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
        "hut_id",
        "source_id",
        "source",
        "bookings",
        "days",
        "start_date",
        "link",
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

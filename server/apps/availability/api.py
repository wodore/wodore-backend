"""API endpoints for hut availability data (dmr).

Provides optimized GeoJSON endpoints using PostgreSQL's native GeoJSON
generation for improved performance compared to Python-based
serialization. The endpoints are registered under the huts router —
route order matters (specific paths before the ``{slug}`` catch-all),
which the huts ``paths`` assembly guarantees.
"""

import datetime

import pydantic
from dmr import Path, Query, modify
from dmr.routing import path
from pydantic import Field

from django.contrib.postgres.aggregates import JSONBAgg
from django.db import models
from django.db.models import Case, F, Max, Q, Value, When
from django.db.models.functions import Coalesce, JSONObject

from server.apps.api.controller import ApiController, cache_headers, raise_not_found
from server.apps.translations import LanguageQuery, activate

from .models import HutAvailability, HutAvailabilityHistory
from .schemas import (
    AvailabilityTrendSchema,
    CurrentAvailabilitySchema,
    HutAvailabilityFeatureCollection,
)
from .utils import parse_availability_date

_DATE_HELP = (
    "Start date. Accepts ISO dates (2026-01-15, 26-01-15), European "
    "format (15.01.2026), or keywords: 'now', 'today', 'weekend'."
)


class DatePathParam(pydantic.BaseModel):
    """Path parameter for date."""

    date: str = Field(description=_DATE_HELP)


class DatePathParamTrend(pydantic.BaseModel):
    """Path parameter for trend endpoint."""

    date: str = Field(description=_DATE_HELP)


class AvailabilityGeoJSONQuery(LanguageQuery):
    """Query parameters for GeoJSON availability endpoint."""

    slugs: str | None = Field(
        None,
        title="Hut Slugs",
        description=(
            "Comma-separated list of hut slugs to filter (e.g., "
            "'aarbiwak,almageller'). If not set, returns all huts."
        ),
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
        description=(
            "Maximum number of huts to return. If not set, returns all matching huts."
        ),
        ge=1,
    )


class CurrentAvailabilityQuery(LanguageQuery):
    """Query parameters for current availability endpoint."""

    days: int = Field(
        1,
        description="Number of days to fetch from start date.",
        ge=1,
        le=365,
    )


class AvailabilityTrendQuery(LanguageQuery):
    """Query parameters for availability trend endpoint."""

    limit: int = Field(
        7,
        description="How many days back to show history from the target date.",
        ge=1,
        le=365,
    )


class _HutSlugPath(pydantic.BaseModel):
    """Hut slug path parameter."""

    slug: str = Field(description="Hut slug")


class _HutDatePath(_HutSlugPath):
    """Hut slug + date path parameters."""

    date: str = Field(description=_DATE_HELP)


class HutAvailabilityGeojsonController(ApiController):
    """Availability as GeoJSON FeatureCollection for map visualization."""

    @modify(
        operation_id="get_hut_availability_geojson",
        headers=cache_headers(600),  # Cache for 10 minutes
    )
    def get(
        self,
        parsed_path: Path[DatePathParam],
        parsed_query: Query[AvailabilityGeoJSONQuery],
    ) -> HutAvailabilityFeatureCollection:
        """Get availability data as GeoJSON FeatureCollection for map visualization."""
        activate(parsed_query.lang)

        start_datetime = parse_availability_date(parsed_path.date)
        start_date = start_datetime.date()

        qs = HutAvailability.objects.filter(
            availability_date__gte=start_date,
            availability_date__lt=start_date
            + datetime.timedelta(days=parsed_query.days),
            hut__is_active=True,
            hut__is_public=True,
        ).select_related("hut", "source_organization", "hut_type")

        if parsed_query.slugs:
            hut_slugs_list = [s.strip().lower() for s in parsed_query.slugs.split(",")]
            qs = qs.filter(hut__slug__in=hut_slugs_list)

        qs = qs.values("hut_id").annotate(
            slug=Max(F("hut__slug")),
            id=F("hut_id"),  # Expose hut_id as 'id' to match schema
            source_id=Max(F("source_id")),
            source=Max(F("source_organization__slug")),
            location=F("hut__location"),  # geometry: same for all records
            type_standard_slug=Max(F("hut__hut_type_open__slug")),
            type_standard_identifier=Max(F("hut__hut_type_open__identifier")),
            type_standard_color=Max(F("hut__hut_type_open__color")),
            type_standard_order=Max(F("hut__hut_type_open__order")),
            type_reduced_slug=Max(F("hut__hut_type_closed__slug")),
            type_reduced_identifier=Max(F("hut__hut_type_closed__identifier")),
            type_reduced_color=Max(F("hut__hut_type_closed__color")),
            type_reduced_order=Max(F("hut__hut_type_closed__order")),
            days=Value(parsed_query.days),
            start_date=Value(start_date.isoformat()),
            data=JSONBAgg(
                JSONObject(
                    date=F("availability_date"),
                    reservation_status=F("reservation_status"),
                    free=F("free"),
                    total=F("total"),
                    free_tolerance=F("free_tolerance"),
                    occupancy_percent=F("occupancy_percent"),
                    occupancy_steps=F("occupancy_steps"),
                    occupancy_status=F("occupancy_status"),
                    # Keep hut_type for backwards compatibility
                    hut_type=Coalesce(F("hut_type__slug"), Value("unknown")),
                    type_slug=Coalesce(F("hut_type__slug"), Value(None)),
                    type_identifier=Coalesce(F("hut_type__identifier"), Value(None)),
                    type_color=Coalesce(F("hut_type__color"), Value(None)),
                    type=Case(
                        When(
                            Q(hut_type_id=F("hut__hut_type_open_id")),
                            then=Value("standard"),
                        ),
                        When(
                            Q(hut_type_id=F("hut__hut_type_closed_id")),
                            then=Value("reduced"),
                        ),
                        default=Value(None),
                        output_field=models.CharField(),
                    ),
                ),
                ordering="availability_date",
            ),
        )

        if parsed_query.limit is not None:
            qs = qs[parsed_query.offset : parsed_query.offset + parsed_query.limit]
        elif parsed_query.offset > 0:
            qs = qs[parsed_query.offset :]

        # Build GeoJSON properties - field names match schema exactly
        properties = [
            "slug",
            "id",
            "source_id",
            "source",
            "days",
            "start_date",
            "type_standard_slug",
            "type_standard_identifier",
            "type_standard_color",
            "type_standard_order",
            "type_reduced_slug",
            "type_reduced_identifier",
            "type_reduced_color",
            "type_reduced_order",
            "data",
        ]

        from server.apps.huts.api.expressions import GeoJSON

        # Generate GeoJSON using PostgreSQL (point geometries need no
        # simplification). Version downgrades are applied uniformly by
        # the API-version middleware for every JSON response.
        return HutAvailabilityFeatureCollection(
            **qs.aggregate(
                GeoJSON(
                    geom_field="location",
                    fields=properties,
                    decimals=5,
                    simplify=False,
                ),
            )["geojson"]
        )


class HutAvailabilityCurrentController(ApiController):
    """Current availability for a hut with booking links."""

    @modify(
        operation_id="get_hut_availability_current",
        headers=cache_headers(300),  # Cache for 5 minutes
    )
    def get(
        self,
        parsed_path: Path[_HutDatePath],
        parsed_query: Query[CurrentAvailabilityQuery],
    ) -> CurrentAvailabilitySchema:
        """Get current availability data for a specific hut.

        Includes detailed metadata and booking links.
        """
        slug = parsed_path.slug
        activate(parsed_query.lang)

        from server.apps.huts.models import Hut

        date_raw = parsed_path.date

        try:
            hut = Hut.objects.get(slug=slug, is_active=True, is_public=True)
        except Hut.DoesNotExist:
            raise_not_found(f"Hut with slug '{slug}' not found")

        start_datetime = parse_availability_date(date_raw)
        start_date = start_datetime.date()

        availabilities = (
            HutAvailability.objects.filter(
                hut=hut,
                availability_date__gte=start_date,
                availability_date__lt=start_date
                + datetime.timedelta(days=parsed_query.days),
            )
            .select_related("source_organization", "hut_type")
            .order_by("availability_date")
        )

        if not availabilities:
            raise_not_found(f"No availability data found for hut '{slug}'")

        first_avail = availabilities[0]

        from server.apps.huts.models import HutOrganizationAssociation

        hut_org_association = HutOrganizationAssociation.objects.filter(
            hut=hut,
            organization=first_avail.source_organization,
            source_id=first_avail.source_id,
        ).first()

        source_link = hut_org_association.link if hut_org_association else ""

        data = []
        for avail in availabilities:
            type_value = None
            if avail.hut_type:
                if avail.hut_type_id == hut.hut_type_open_id:
                    type_value = "standard"
                elif avail.hut_type_id == hut.hut_type_closed_id:
                    type_value = "reduced"

            data.append(
                {
                    "date": avail.availability_date,
                    "reservation_status": avail.reservation_status,
                    "free": avail.free,
                    "total": avail.total,
                    "free_tolerance": avail.free_tolerance,
                    "occupancy_percent": avail.occupancy_percent,
                    "occupancy_steps": avail.occupancy_steps,
                    "occupancy_status": avail.occupancy_status,
                    # Keep hut_type for backwards compatibility
                    "hut_type": avail.hut_type.slug if avail.hut_type else "unknown",
                    "type_slug": avail.hut_type.slug if avail.hut_type else None,
                    "type_identifier": avail.hut_type.identifier
                    if avail.hut_type
                    else None,
                    "type_color": avail.hut_type.color if avail.hut_type else None,
                    "type": type_value,
                    "link": avail.link,
                    "first_checked": avail.first_checked,
                    "last_checked": avail.last_checked,
                }
            )

        return CurrentAvailabilitySchema(
            slug=hut.slug,
            id=hut.id,
            source_id=first_avail.source_id,
            source=first_avail.source_organization.slug,
            source_link=source_link,
            days=parsed_query.days,
            start_date=start_date,
            type_standard_slug=hut.hut_type_open.slug if hut.hut_type_open else None,
            type_standard_identifier=hut.hut_type_open.identifier
            if hut.hut_type_open
            else None,
            type_standard_color=hut.hut_type_open.color if hut.hut_type_open else None,
            type_standard_order=hut.hut_type_open.order if hut.hut_type_open else None,
            type_reduced_slug=hut.hut_type_closed.slug if hut.hut_type_closed else None,
            type_reduced_identifier=hut.hut_type_closed.identifier
            if hut.hut_type_closed
            else None,
            type_reduced_color=hut.hut_type_closed.color
            if hut.hut_type_closed
            else None,
            type_reduced_order=hut.hut_type_closed.order
            if hut.hut_type_closed
            else None,
            data=data,
        )


class HutAvailabilityTrendController(ApiController):
    """Historical availability trend for a target date."""

    @modify(
        operation_id="get_hut_availability_trend",
        headers=cache_headers(600),  # Cache for 10 minutes
    )
    def get(
        self,
        parsed_path: Path[_HutDatePath],
        parsed_query: Query[AvailabilityTrendQuery],
    ) -> AvailabilityTrendSchema:
        """Get historical availability trend data.

        Shows how availability changed over time for a specific date.
        """
        slug = parsed_path.slug
        activate(parsed_query.lang)

        from server.apps.huts.models import Hut

        try:
            hut = Hut.objects.get(slug=slug, is_active=True, is_public=True)
        except Hut.DoesNotExist:
            raise_not_found(f"Hut with slug '{slug}' not found")

        date_raw = parsed_path.date
        target_datetime = parse_availability_date(date_raw)
        target_date = target_datetime.date()

        period_start = target_datetime - datetime.timedelta(days=parsed_query.limit)
        period_end = target_datetime

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
            raise_not_found(
                f"No historical data found for hut {slug!r} on date "
                f"{target_date} within the specified period",
            )

        data = [
            {
                "date": h.availability_date,
                "free": h.free,
                "total": h.total,
                "free_tolerance": h.free_tolerance,
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
            data=data,  # type: ignore[arg-type]  # schema list coercion
        )


paths = [
    path(
        "availability/<str:date>.geojson",
        HutAvailabilityGeojsonController.as_view(),
        name="get_hut_availability_geojson",
    ),
    path(
        "<str:slug>/availability/<str:date>",
        HutAvailabilityCurrentController.as_view(),
        name="get_hut_availability_current",
    ),
    path(
        "<str:slug>/availability/<str:date>/trend",
        HutAvailabilityTrendController.as_view(),
        name="get_hut_availability_trend",
    ),
]

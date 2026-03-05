"""
Pydantic schemas for availability API responses.
"""

import datetime
import typing as t

from geojson_pydantic import Feature, FeatureCollection, Point
from hut_services.core.schema import OccupancyStatusEnum, ReservationStatusEnum
from pydantic import BaseModel, Field


class AvailabilityDaySchema(BaseModel):
    """Single day's availability data for a hut."""

    date: datetime.date = Field(..., description="Availability date")
    reservation_status: ReservationStatusEnum = Field(
        ...,
        description="Reservation status (unknown, possible, not_possible, not_online)",
    )
    free: int = Field(..., description="Number of free places", ge=0)
    total: int = Field(..., description="Total number of places", ge=0)
    occupancy_percent: float = Field(
        ..., description="Occupancy percentage (0-100)", ge=0, le=100
    )
    occupancy_steps: int = Field(
        ...,
        description="Occupancy in discrete steps (0-100, increments of 10)",
        ge=0,
        le=100,
    )
    occupancy_status: OccupancyStatusEnum = Field(
        ..., description="Occupancy status (empty, low, medium, high, full, unknown)"
    )
    hut_type: str = Field(
        default="unknown", description="Hut type on this date (e.g., 'hut', 'bivouac')"
    )
    type_slug: str | None = Field(
        None, description="Hut type slug (e.g., 'hut', 'bivouac')"
    )
    type_identifier: str | None = Field(
        None, description="Hut type identifier symbol (emoji)"
    )
    type_color: str | None = Field(None, description="Hut type color as hex code")
    type: str | None = Field(
        None,
        description="Either 'standard' or 'reduced' depending on which hut type applies",
    )


class HutAvailabilityPropertiesSchema(BaseModel):
    """Properties for a hut availability GeoJSON feature."""

    slug: str = Field(..., description="Hut slug identifier")
    id: int = Field(..., description="Hut database ID")
    source_id: str = Field(
        ..., description="External source organization's ID for this hut"
    )
    source: str = Field(
        ..., description="Source organization slug (e.g., 'hrs', 'sac')"
    )
    source_link: str = Field(
        ..., description="External link to the hut page on the source website"
    )
    days: int = Field(..., description="Number of days of availability data", ge=1)
    start_date: datetime.date = Field(
        ..., description="Start date of availability period"
    )
    type_standard_slug: str | None = Field(
        None, description="Hut type slug in standard state (summer/fully open)"
    )
    type_standard_identifier: str | None = Field(
        None, description="Hut type identifier symbol in standard state"
    )
    type_standard_color: str | None = Field(
        None, description="Hut type color as hex code in standard state"
    )
    type_standard_order: int | None = Field(
        None, description="Hut type display order in standard state"
    )
    type_reduced_slug: str | None = Field(
        None, description="Hut type slug in reduced state (winter/closed)"
    )
    type_reduced_identifier: str | None = Field(
        None, description="Hut type identifier symbol in reduced state"
    )
    type_reduced_color: str | None = Field(
        None, description="Hut type color as hex code in reduced state"
    )
    type_reduced_order: int | None = Field(
        None, description="Hut type display order in reduced state"
    )
    data: t.Sequence[AvailabilityDaySchema] = Field(
        ..., description="List of availability data for each day"
    )


# GeoJSON types
HutAvailabilityFeature = Feature[Point, HutAvailabilityPropertiesSchema]


class HutAvailabilityFeatureCollection(FeatureCollection[HutAvailabilityFeature]):
    """GeoJSON FeatureCollection of hut availability data."""

    pass


# Schemas for current availability endpoint
class CurrentAvailabilityDaySchema(BaseModel):
    """Single day's current availability data with metadata."""

    date: datetime.date = Field(..., description="Availability date")
    reservation_status: ReservationStatusEnum = Field(
        ...,
        description="Reservation status (unknown, possible, not_possible, not_online)",
    )
    free: int = Field(..., description="Number of free places", ge=0)
    total: int = Field(..., description="Total number of places", ge=0)
    occupancy_percent: float = Field(
        ..., description="Occupancy percentage (0-100)", ge=0, le=100
    )
    occupancy_steps: int = Field(
        ...,
        description="Occupancy in discrete steps (0-100, increments of 10)",
        ge=0,
        le=100,
    )
    occupancy_status: OccupancyStatusEnum = Field(
        ..., description="Occupancy status (empty, low, medium, high, full, unknown)"
    )
    hut_type: str = Field(
        default="unknown", description="Hut type on this date (e.g., 'hut', 'bivouac')"
    )
    type_slug: str | None = Field(
        None, description="Hut type slug (e.g., 'hut', 'bivouac')"
    )
    type_identifier: str | None = Field(
        None, description="Hut type identifier symbol (emoji)"
    )
    type_color: str | None = Field(None, description="Hut type color as hex code")
    type: str | None = Field(
        None,
        description="Either 'standard' or 'reduced' depending on which hut type applies",
    )
    link: str = Field(..., description="Booking link for this date")
    first_checked: datetime.datetime = Field(
        ..., description="When this availability was first recorded"
    )
    last_checked: datetime.datetime = Field(
        ..., description="When this availability was last checked"
    )


class CurrentAvailabilitySchema(BaseModel):
    """Current availability data for a specific hut."""

    slug: str = Field(..., description="Hut slug identifier")
    id: int = Field(..., description="Hut database ID")
    source_id: str = Field(
        ..., description="External source organization's ID for this hut"
    )
    source_link: str = Field(
        ..., description="External source organization's link for this hut"
    )
    source: str = Field(
        ..., description="Source organization slug (e.g., 'hrs', 'sac')"
    )
    days: int = Field(..., description="Number of days of availability data", ge=1)
    start_date: datetime.date = Field(
        ..., description="Start date of availability period"
    )
    type_standard_slug: str | None = Field(
        None, description="Hut type slug in standard state (summer/fully open)"
    )
    type_standard_identifier: str | None = Field(
        None, description="Hut type identifier symbol in standard state"
    )
    type_standard_color: str | None = Field(
        None, description="Hut type color as hex code in standard state"
    )
    type_standard_order: int | None = Field(
        None, description="Hut type display order in standard state"
    )
    type_reduced_slug: str | None = Field(
        None, description="Hut type slug in reduced state (winter/closed)"
    )
    type_reduced_identifier: str | None = Field(
        None, description="Hut type identifier symbol in reduced state"
    )
    type_reduced_color: str | None = Field(
        None, description="Hut type color as hex code in reduced state"
    )
    type_reduced_order: int | None = Field(
        None, description="Hut type display order in reduced state"
    )
    data: t.Sequence[CurrentAvailabilityDaySchema] = Field(
        ..., description="List of current availability data for each day"
    )


# Schemas for trend/history endpoint
class AvailabilityTrendDaySchema(BaseModel):
    """Single historical availability data point."""

    date: datetime.date = Field(
        ..., description="Availability date this data applies to"
    )
    free: int = Field(..., description="Number of free places", ge=0)
    total: int = Field(..., description="Total number of places", ge=0)
    occupancy_percent: float = Field(
        ..., description="Occupancy percentage (0-100)", ge=0, le=100
    )
    occupancy_status: OccupancyStatusEnum = Field(
        ..., description="Occupancy status (empty, low, medium, high, full, unknown)"
    )
    reservation_status: ReservationStatusEnum = Field(
        ...,
        description="Reservation status (unknown, possible, not_possible, not_online)",
    )
    hut_type: str = Field(
        default="unknown", description="Hut type on this date (e.g., 'hut', 'bivouac')"
    )
    first_checked: datetime.datetime = Field(
        ..., description="When this state was first observed"
    )
    last_checked: datetime.datetime = Field(
        ..., description="When this state was last confirmed"
    )


class AvailabilityTrendSchema(BaseModel):
    """Historical availability trend data for a specific hut and date."""

    slug: str = Field(..., description="Hut slug identifier")
    id: int = Field(..., description="Hut database ID")
    target_date: datetime.date = Field(
        ..., description="The date for which trend data is shown"
    )
    period_start: datetime.date = Field(
        ..., description="Start of the trend period (target_date - limit days)"
    )
    period_end: datetime.date = Field(
        ..., description="End of the trend period (target_date)"
    )
    data: t.Sequence[AvailabilityTrendDaySchema] = Field(
        ...,
        description="Historical availability changes, ordered by first_checked (newest first)",
    )

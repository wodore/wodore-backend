import datetime
import typing as t

from geojson_pydantic import Feature, FeatureCollection, Point
from hut_services import LocationSchema
from hut_services.core.schema import (
    BookingSchema,
    OccupancyStatusEnum,
    ReservationStatusEnum,
)
from pydantic import BaseModel, Field, model_validator

# from pydantic import ConfigDict
from django.conf import settings  # noqa: F401


class HutBookingSchema(BaseModel):
    link: str
    date: datetime.date
    reservation_status: ReservationStatusEnum
    free: int
    total: int
    occupancy_percent: float
    occupancy_steps: int
    occupancy_status: OccupancyStatusEnum
    hut_type: str = "unknown"

    @model_validator(mode="before")
    @classmethod
    def check_card_number_omitted(cls, data: t.Any) -> t.Any:
        if isinstance(data, BookingSchema):
            model = data.model_dump()
            model.update(data.places.model_dump())
        elif isinstance(data, dict) and "places" in data:
            model = data
            model.update(data["places"])
        else:
            model = data
        return model


class HutBookingsProps(BaseModel):
    slug: str
    hut_id: int = Field(..., alias="id")
    source: str = Field(..., description="Source slug, e.g. hrs")
    days: int
    link: str
    start_date: datetime.date
    bookings: t.Sequence[HutBookingSchema]


HutBookingsFeature = Feature[Point, HutBookingsProps]


class HutBookingsSchema(HutBookingsProps):
    location: LocationSchema

    def as_feature(self) -> HutBookingsFeature:
        # props = self.model_dump(exclude={"location"}, by_alias=True)
        return HutBookingsFeature(
            id=self.hut_id,
            type="Feature",
            geometry=Point(type="Point", coordinates=self.location.lon_lat),
            properties=self,
        )


class HutBookingsFeatureCollection(FeatureCollection[HutBookingsFeature]): ...

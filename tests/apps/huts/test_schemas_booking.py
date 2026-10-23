"""Tests for the booking schema flattening layer (core -> backend)."""

import datetime

from hut_services.core.schema import (
    BookingSchema,
    OccupancyStatusEnum,
    PlacesSchema,
    ReservationStatusEnum,
)

from server.apps.huts.schemas_booking import HutBookingSchema


class TestPlacesFlattening:
    def _booking(self, places: PlacesSchema) -> BookingSchema:
        return BookingSchema(
            date=datetime.date(2027, 7, 1),
            reservation_status=ReservationStatusEnum.possible,
            unattended=False,
            places=places,
            link="https://example.com",
        )

    def test_free_tolerance_flattens_from_places(self) -> None:
        booking = self._booking(PlacesSchema(free=14, total=42, free_tolerance=5))
        flat = HutBookingSchema.model_validate(booking)
        assert flat.free == 14
        assert flat.total == 42
        assert flat.free_tolerance == 5

    def test_exact_sources_default_zero(self) -> None:
        booking = self._booking(PlacesSchema(free=3, total=30))
        flat = HutBookingSchema.model_validate(booking)
        assert flat.free_tolerance == 0

    def test_unknown_free_keeps_tolerance_zero(self) -> None:
        booking = self._booking(PlacesSchema(free=None, total=30))
        flat = HutBookingSchema.model_validate(booking)
        assert flat.free is None
        assert flat.free_tolerance == 0
        assert flat.occupancy_status == OccupancyStatusEnum.free_unknown

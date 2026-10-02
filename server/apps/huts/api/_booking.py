"""Deprecated hut bookings endpoints (sunset: see apiversions registry).

``/v1/huts/bookings`` and ``/v1/huts/bookings.geojson`` have been
OpenAPI-deprecated for a while (replacement:
``/huts/availability.geojson``). The versioning rollout gives them a
concrete sunset; past that date the handlers answer 410 via
``guard_endpoint_sunset`` (the former ninja ``wrap_api`` machinery,
now explicit).

Auth stays disabled: the Zitadel role vocabulary ('perm:bookings') does
not exist for local auth users, so enabling this would lock the
endpoints out of local mode. Revisit together with the roles strategy.
"""

from http import HTTPStatus
from typing import Literal

from dmr import APIError, Query, ResponseSpec, modify
from dmr.headers import HeaderSpec
from dmr.routing import path
from pydantic import Field

from server.apps.api.controller import ApiController, ErrorDetail
from server.apps.api.error_codes import ErrorCode
from server.apps.apiversions.registry import guard_endpoint_sunset
from server.apps.translations import LanguageQuery, override

from ..models import Hut
from ..schemas_booking import (
    HutBookingsFeatureCollection,
    HutBookingsSchema,
)


class HutBookingsQuery(LanguageQuery):
    """Query parameters for the bookings endpoints."""

    slugs: str | None = Field(
        None,
        title="Slugs",
        description="Comma separated list with slugs to use, per default all.",
    )
    days: int = Field(1, description="Show bookings for this many days.")
    date: str | Literal["now", "weekend"] = Field(
        "now",
        description="Date to start with bookings (yyyy-mm-dd, 'now' or 'weekend').",
    )
    request_interval: float | None = Field(
        None,
        title="Request interval",
        description=(
            "Time in seconds to wait between requests to the booking "
            "service for each hut. If not set uses recommanded default "
            "value."
        ),
    )


def _hut_slugs_list(slugs: str | None) -> list[str] | None:
    if slugs:
        return [s.strip().lower() for s in slugs.split(",")]
    return None


_UNAVAILABLE = ResponseSpec(
    ErrorDetail,
    status_code=HTTPStatus.SERVICE_UNAVAILABLE,
    description="Booking service unavailable. Please retry later.",
)

# 410 after the endpoint sunset (headers set by the endpoint guard and
# the API-version middleware — documented but not runtime-validated).
_SUNSET = ResponseSpec(
    ErrorDetail,
    status_code=HTTPStatus.GONE,
    description="Endpoint sunset (see Deprecation/Sunset headers).",
    headers={
        "Deprecation": HeaderSpec(required=False, skip_validation=True),
        "Sunset": HeaderSpec(required=False, skip_validation=True),
        "Link": HeaderSpec(required=False, skip_validation=True),
    },
)


class _BookingsController(ApiController):
    """Shared bookings fetch + sunset guard."""

    query_model = HutBookingsQuery
    operation_id: str  # set by subclasses

    def _fetch(self, parsed_query: HutBookingsQuery):
        guard_endpoint_sunset(self.operation_id)
        hut_slugs_list = _hut_slugs_list(parsed_query.slugs)
        with override(parsed_query.lang):
            res = Hut.get_bookings(
                hut_slugs=hut_slugs_list,
                days=parsed_query.days,
                date=parsed_query.date,
                lang=parsed_query.lang,
                request_interval=parsed_query.request_interval,
            )
            if not res:
                raise APIError(
                    {
                        "code": ErrorCode.service_unavailable,
                        "detail": "Booking service unavailable. Please retry later.",
                    },
                    status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                )
            return res


class HutBookingsController(_BookingsController):
    """Hut bookings as a list (deprecated)."""

    operation_id = "get_hut_bookings"

    @modify(
        operation_id="get_hut_bookings",
        deprecated=True,
        extra_responses=[_UNAVAILABLE, _SUNSET],
        summary="Get hut bookings (deprecated)",
        description=(
            "**DEPRECATED**: Use `/huts/availability.geojson` instead. "
            "This endpoint will be removed in a future version."
        ),
    )
    def get(self, parsed_query: Query[HutBookingsQuery]) -> list[HutBookingsSchema]:
        """Get hut bookings (deprecated — use availability.geojson)."""
        return self._fetch(parsed_query)


class HutBookingsGeojsonController(_BookingsController):
    """Hut bookings as GeoJSON (deprecated)."""

    operation_id = "get_hut_bookings_geojson"

    @modify(
        operation_id="get_hut_bookings_geojson",
        deprecated=True,
        extra_responses=[_UNAVAILABLE, _SUNSET],
        summary="Get hut bookings as GeoJSON (deprecated)",
        description=(
            "**DEPRECATED**: Use `/huts/availability.geojson` instead. "
            "This endpoint will be removed in a future version."
        ),
    )
    def get(
        self, parsed_query: Query[HutBookingsQuery]
    ) -> HutBookingsFeatureCollection:
        """Get hut bookings as GeoJSON (deprecated)."""
        huts = Hut.get_bookings(
            hut_slugs=_hut_slugs_list(parsed_query.slugs),
            days=parsed_query.days,
            date=parsed_query.date,
            lang=parsed_query.lang,
        )
        guard_endpoint_sunset(self.operation_id)
        features = [h.as_feature() for h in huts]
        res = HutBookingsFeatureCollection(type="FeatureCollection", features=features)
        if not res:
            raise APIError(
                {
                    "code": ErrorCode.service_unavailable,
                    "detail": "Booking service unavailable. Please retry later.",
                },
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            )
        return res


paths = [
    path("bookings", HutBookingsController.as_view(), name="get_hut_bookings"),
    path(
        "bookings.geojson",
        HutBookingsGeojsonController.as_view(),
        name="get_hut_bookings_geojson",
    ),
]

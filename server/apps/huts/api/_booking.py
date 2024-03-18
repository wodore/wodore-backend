import datetime
from typing import Literal

from geojson_pydantic import FeatureCollection
from ninja import Field, Query, Schema
from ninja.security import django_auth

from django.http import HttpRequest

# from django.contrib.gis.db.models.functions import AsGeoJSON
# from django.contrib.postgres.aggregates import JSONBAgg
from server.apps.translations import (
    LanguageParam,
    override,
    with_language_param,
)

from ..models import Hut
from ..schemas_booking import (
    HutBookingsFeatureCollection,
    HutBookingsSchema,
)
from ._router import router


class HutBookingsQuery(Schema):
    slugs: str | None = Field(
        None, title="Slugs", description="Comma separated list with slugs to use, per default all."
    )
    days: int = Field(1, description="Show bookings for this many days.")
    # date: datetime.date | Literal["now"] = Field("now", description="Date to start with booking (yyyy-mm-dd or now).")
    date: str | Literal["now"] = Field("now", description="Date to start with booking (yyyy-mm-dd or now).")


def _hut_slugs_list(slugs: str | None) -> list[str] | None:
    if slugs:
        hut_slugs_list: list[str] | None = [s.strip().lower() for s in slugs.split(",")]
    else:
        hut_slugs_list = None
    return hut_slugs_list


@router.get("bookings", response=list[HutBookingsSchema], operation_id="get_hut_bookings", auth=django_auth)
@with_language_param("lang")
def get_hut_bookings(  # type: ignore  # noqa: PGH003
    request: HttpRequest, lang: LanguageParam, queries: Query[HutBookingsQuery]
) -> list[HutBookingsSchema]:
    hut_slugs_list = _hut_slugs_list(queries.slugs)
    with override(lang):
        return Hut.get_bookings(hut_slugs=hut_slugs_list, days=queries.days, date=queries.date, lang=lang)


@router.get("bookings.geojson", response=HutBookingsFeatureCollection, operation_id="get_hut_bookings_geojson")
@with_language_param("lang")
def get_hut_bookings_geojson(  # type: ignore  # noqa: PGH003
    request: HttpRequest, lang: LanguageParam, queries: Query[HutBookingsQuery]
) -> FeatureCollection:
    hut_slugs_list = _hut_slugs_list(queries.slugs)
    huts = Hut.get_bookings(hut_slugs=hut_slugs_list, days=queries.days, date=queries.date, lang=lang)
    features = [h.as_feature() for h in huts]
    return HutBookingsFeatureCollection(type="FeatureCollection", features=features)

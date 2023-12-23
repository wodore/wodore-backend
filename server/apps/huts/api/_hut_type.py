from os import wait
from re import I
from time import perf_counter
from typing import List

import msgspec
from geojson_pydantic import Feature, FeatureCollection
from ninja import Query, Router
from ninja.errors import HttpError

from django.contrib.gis.db.models.functions import AsGeoJSON
from django.contrib.postgres.aggregates import JSONBAgg
from django.core.serializers import serialize
from django.db import IntegrityError
from django.db.models import F, TextField
from django.db.models.functions import Cast, JSONObject, Lower
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404

from server.apps.api.query import FieldsParam
from server.apps.translations import (
    LanguageParam,
    activate,
    override,
    with_language_param,
)

from ..models import HutType
from ..schemas import HutTypeDetailSchema
from ._router import router


@router.get("types/list", response=list[HutTypeDetailSchema], exclude_unset=True)
@with_language_param("lang")
def list_hut_types(  # type: ignore  # noqa: PGH003
    request: HttpRequest,
    lang: LanguageParam,
    fields: Query[FieldsParam[HutTypeDetailSchema]],
) -> list[HutTypeDetailSchema]:
    qs = HutType.objects.all().order_by("level", "slug")
    fields.update_default(HutType.FIELDS)
    with override(lang):
        # return qs
        return fields.validate(list(qs))
        # return fields.validate(list(huts_db))


@router.get("types/records", response=dict[str, HutTypeDetailSchema], exclude_unset=True)
@with_language_param("lang")
def list_hut_types_records(  # type: ignore  # noqa: PGH003
    request: HttpRequest,
    lang: LanguageParam,
    fields: Query[FieldsParam[HutTypeDetailSchema]],
) -> list[HutTypeDetailSchema]:
    qs = HutType.objects.all().order_by("level", "slug")
    fields.update_default(HutType.FIELDS)
    with override(lang):
        # return qs
        hts = fields.validate(list(qs))
        return {ht.slug: ht for ht in hts}
        # return fields.validate(list(huts_db))

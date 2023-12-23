from os import wait
from re import I
from typing import List

from time import perf_counter
import msgspec
from geojson_pydantic import Feature, FeatureCollection
from ninja import Query, Router
from ninja.errors import HttpError

from django.contrib.gis.db.models.functions import AsGeoJSON
from django.contrib.postgres.aggregates import JSONBAgg
from django.core.serializers import serialize
from django.db import IntegrityError
from django.db.models import F
from django.db.models.functions import JSONObject, Lower
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404

from server.apps.api.query import FieldsParam
from server.apps.translations import LanguageParam, override, with_language_param, activate

from ..models import Hut
from ..schemas import HutSchemaOptional
from ._router import router
from .expressions import GeoJSON


@router.get("huts", response=List[HutSchemaOptional], exclude_unset=True)
@with_language_param("lang")
def list_huts(  # type: ignore  # noqa: PGH003
    request: HttpRequest,
    lang: LanguageParam,
    fields: Query[FieldsParam[HutSchemaOptional]],
    offset: int = 0,
    limit: int | None = None,
    is_public: bool | None = None,
) -> list[HutSchemaOptional]:
    huts_db = Hut.objects.select_related("owner").all().filter(is_active=True)

    huts_db = huts_db.select_related("type", "owner").annotate(
        orgs=JSONBAgg(
            JSONObject(
                logo="organizations__logo",
                fullname="organizations__fullname_i18n",
                slug="organizations__slug",
                name="organizations__name_i18n",
                link="orgs_source__link",
            )
        )
    )
    if limit is not None:
        huts_db = huts_db[offset : offset + limit]
    if isinstance(is_public, bool):
        huts_db = huts_db.filter(is_public=is_public)
    with override(lang):
        return huts_db
        # return fields.validate(list(huts_db))


@router.get("huts.geojson", response=FeatureCollection)
@with_language_param("lang")
def list_huts_geojson(  # type: ignore  # noqa: PGH003
    request: HttpRequest,
    response: HttpResponse,
    lang: LanguageParam,
    offset: int = 0,
    limit: int | None = None,
    is_public: bool | None = None,
) -> list[HutSchemaOptional]:
    # t1_start = perf_counter()
    activate(lang)
    huts_db = (
        Hut.objects.select_related("type", "owner")
        .filter(is_active=True)
        .annotate(
            type_slug=F("type__slug"),
            hut_name=F("name"),
            hut_owner=JSONObject(
                name="owner__name_i18n",
                slug="owner__slug",
            )
            # hut_type=JSONObject(
            #    symbol="type__symbol",
            #    symbol_simple="type__symbol_simple",
            #    slug="type__slug",
            #    name="type__name_i18n",
            # )
        )
        # .values("type_slug", "hut_name", "hut_owner")
        # .annotate(owner=F("hut_owner"))
    )
    huts_db = huts_db.prefetch_related("organizations").annotate(
        orgs=JSONBAgg(
            JSONObject(
                # logo="organizations__logo",
                # fullname="organizations__fullname_i18n",
                slug="organizations__slug",
                # name="organizations__name_i18n",
                link="orgs_source__link",
            )
        )
    )

    if limit is not None:
        huts_db = huts_db[offset : offset + limit]
    if isinstance(is_public, bool):
        huts_db = huts_db.filter(is_public=is_public)
    # with override(lang):
    geojson = huts_db.aggregate(
        GeoJSON(
            geom_field="location",
            fields=[
                "id",
                "slug",
                "hut_name",
                "orgs",
                "type_slug",
                "hut_owner",
                "elevation",
                "capacity",
                "capacity_shelter",
            ],
            decimals=5,
        )
    )["geojson"]
    # return geojson # use pydantic
    # t1_stop = perf_counter()
    response.write(msgspec.json.encode(geojson))
    # t2_stop = perf_counter()
    # print(f"Database: {(t1_stop - t1_start)*1000} ms")
    # print(f"Encode:   {(t2_stop - t1_stop)*1000} ms")
    # print(f"Total:    {(t2_stop - t1_start)*1000} ms")
    return response


@router.get("huts-serializer.geojson", response=FeatureCollection)
@with_language_param("lang")
def list_huts_geojson(  # type: ignore  # noqa: PGH003
    request: HttpRequest,
    response: HttpResponse,
    lang: LanguageParam,
    offset: int = 0,
    limit: int | None = None,
    is_public: bool | None = None,
) -> list[HutSchemaOptional]:
    huts_db = Hut.objects.select_related("type").filter(is_active=True).annotate(type_slug=F("type__slug"))
    if limit is not None:
        huts_db = huts_db[offset : offset + limit]
    if isinstance(is_public, bool):
        huts_db = huts_db.filter(is_public=is_public)
    with override(lang):
        geojson = serialize(
            "geojson",
            huts_db,
            geometry_field="location",
            fields=["slug", "name", "type", "elevation", "capacity", "capacity_shelter"],
        )
        response.write(geojson)
        return response
        # return list(huts_db)


# @router.post("/", response=OrganizationOptional)
# def create_organization(request, payload: OrganizationCreate):
#    last_elem = Organization.objects.values("order").last() or {}
#    order = last_elem.get("order", -1) + 1
#    pay_dict = payload.model_dump()
#    pay_dict["order"] = order
#    try:
#        org = Organization.objects.create(**pay_dict)
#    except IntegrityError as e:
#        raise HttpError(400, str(e))
#    return org
#
#
# @router.get("/{slug}", response=OrganizationOptional, exclude_unset=True)
# @with_language_param()
# def organization_details(request, slug: str, lang: LanguageParam, fields: Query[FieldsParam[OrganizationOptional]]):
#    fields.update_default("__all__")
#    obj = fields.validate(get_object_or_404(Organization, slug=slug))
#    return obj
#
#
# @router.put("/{slug}", response=OrganizationOptional)
# def update_organization(request, slug: str, payload: OrganizationUpdate):
#    org = get_object_or_404(Organization, slug=slug)
#    for attr, value in payload.model_dump(exclude_unset=True).items():
#        setattr(org, attr, value)
#    org.save()
#    return org
#
#
# @router.delete("/{slug}")
# def delete_organization(request, slug: str):
#    org = get_object_or_404(Organization, slug=slug)
#    org.delete()
#    return {"success": True}
#

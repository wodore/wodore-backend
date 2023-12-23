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
    huts_db = Hut.objects.select_related("hut_owner").all().filter(is_active=True)

    huts_db = huts_db.select_related("hut_type_open", "hut_type_closed", "hut_owner").annotate(
        orgs=JSONBAgg(
            JSONObject(
                logo="org_set__logo",
                fullname="org_set__fullname_i18n",
                slug="org_set__slug",
                name="org_set__name_i18n",
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
    embed_all: bool = False,
    embed_type: bool = False,
    embed_owner: bool = False,
    embed_capacity: bool = False,
    embed_organizations: bool = False,
    include_elevation: bool = False,
    include_name: bool = False,
) -> list[HutSchemaOptional]:
    # t1_start = perf_counter()
    activate(lang)
    qs = Hut.objects.filter(is_active=True)
    properties = [
        "id",
        "slug",
    ]
    if embed_all or include_elevation:
        properties.append("elevation")
    if embed_all or include_name:
        properties.append("name")
    if embed_all or embed_type:
        qs = qs.select_related("hut_type_open", "hut_type_closed").annotate(
            type=JSONObject(
                open="hut_type_open__slug",
                closed="hut_type_closed__slug",
            ),
        )

        properties.append("type")
    if embed_all or embed_owner:
        qs = qs.select_related("hut_owner").annotate(
            owner=JSONObject(
                name="hut_owner__name_i18n",
                slug="hut_owner__slug",
            )
        )
        properties.append("owner")
    if embed_all or embed_capacity:
        qs = qs.annotate(
            capacity=JSONObject(
                open="capacity_open",
                closed="capacity_closed",
            )
        )
        properties.append("capacity")
    if embed_all or embed_organizations:
        qs = qs.prefetch_related("org_set").annotate(
            organizations=JSONBAgg(
                JSONObject(
                    # logo="org_set__logo",
                    # fullname="org_set__fullname_i18n",
                    slug="org_set__slug",
                    # name="org_set__name_i18n",
                    link="orgs_source__link",
                )
            )
        )
        properties.append("organizations")
    if limit is not None:
        qs = qs[offset : offset + limit]
    if isinstance(is_public, bool):
        qs = qs.filter(is_public=is_public)
    # with override(lang):
    geojson = qs.aggregate(
        GeoJSON(
            geom_field="location",
            fields=properties,
            decimals=5,
        ),
    )["geojson"]
    # TODO: maybe get it directly as str?
    response.write(msgspec.json.encode(geojson))
    return response


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

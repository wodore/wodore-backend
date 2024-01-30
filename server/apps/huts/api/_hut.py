import typing as t
from typing import List

import msgspec
from benedict import benedict
from geojson_pydantic import FeatureCollection
from ninja import Query

# from ninja.errors import HttpError
from django.conf import settings
from django.contrib.postgres.aggregates import JSONBAgg
from django.db.models import F, Value
from django.db.models.functions import Concat, JSONObject  # , Lower
from django.http import Http404, HttpRequest, HttpResponse
from django.urls import reverse_lazy

from server.apps.api.query import FieldsParam, TristateEnum
from server.apps.translations import (
    LanguageParam,
    activate,
    with_language_param,
)

from ..models import Hut
from ..schemas import HutSchemaDetails, HutSchemaOptional
from ._router import router
from .expressions import GeoJSON


@router.get("huts", response=List[HutSchemaOptional], exclude_unset=True, operation_id="get_huts")
@with_language_param("lang")
def get_huts(  # type: ignore  # noqa: PGH003
    request: HttpRequest,
    lang: LanguageParam,
    # fields: Query[FieldsParam[HutSchemaOptional]],
    offset: int = 0,
    limit: int | None = None,
    is_modified: TristateEnum = TristateEnum.unset,
    is_public: TristateEnum = TristateEnum.true,  # needs permission
    is_active: TristateEnum = TristateEnum.true,  # needs permission
) -> list[Hut]:
    """Get a list with huts."""
    activate(lang)
    huts_db = Hut.objects.select_related("hut_owner").all()
    if isinstance(is_modified, bool):
        huts_db = huts_db.filter(is_modified=is_modified.bool)
    if isinstance(is_active, bool):
        huts_db = huts_db.filter(is_active=is_active.bool)
    if isinstance(is_public, bool):
        huts_db = huts_db.filter(is_public=is_public.bool)

    huts_db = huts_db.select_related("hut_type_open", "hut_type_closed", "hut_owner").annotate(
        sources=JSONBAgg(
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
    return huts_db
    # return fields.validate(list(huts_db))


def get_json_obj(values: dict[str, t.Any], flat: bool = False) -> dict[str, JSONObject | F]:
    if flat:
        return {k: F(str(v)) for k, v in benedict(values).flatten(separator="_").items()}
    new_vals = {}
    for key, value in values.items():
        new_vals[key] = JSONObject(**get_json_obj(value)) if isinstance(value, dict) else value
    return new_vals


@router.get("huts.geojson", response=FeatureCollection, operation_id="get_huts_geojson")
@with_language_param("lang")
def get_huts_geojson(  # type: ignore  # noqa: PGH003
    request: HttpRequest,
    response: HttpResponse,
    lang: LanguageParam,
    offset: int = 0,
    limit: int | None = None,
    # is_public: bool | None = None, # needs permission
    embed_all: bool = False,
    embed_type: bool = False,
    embed_owner: bool = False,
    embed_capacity: bool = False,
    embed_sources: bool = False,
    include_elevation: bool = False,
    include_name: bool = False,
    flat: bool = True,
) -> HttpResponse:
    activate(lang)
    qs = Hut.objects.filter(is_active=True, is_public=True)
    # if isinstance(is_public, bool):
    #     qs = qs.filter(is_public=is_public)
    properties = [
        "id",
        "slug",
    ]
    if embed_all or include_elevation:
        properties.append("elevation")
    if embed_all or include_name:
        properties.append("name")
    if embed_all or embed_type:
        annot = get_json_obj(
            flat=flat,
            values={
                "type": {
                    "open": {
                        "slug": "hut_type_open__slug",
                        "level": "hut_type_open__level",
                    },
                    "closed": {
                        "slug": "hut_type_closed__slug",
                        "level": "hut_type_closed__level",
                    },
                },
            },
        )
        qs = qs.select_related("hut_type_open", "hut_type_closed").annotate(**annot)
        properties += list(annot.keys())
    if embed_all or embed_owner:
        annot = get_json_obj(
            flat=flat,
            values={
                "owner": {
                    "name": "hut_owner__name_i18n",
                    "slug": "hut_owner__slug",
                }
            },
        )
        qs = qs.select_related("hut_owner").annotate(**annot)
        properties += list(annot.keys())
    if embed_all or embed_capacity:
        annot = get_json_obj(
            flat=flat,
            values={
                "capacity": {
                    "if_open": "capacity_open",
                    "if_closed": "capacity_closed",
                }
            },
        )
        qs = qs.annotate(**annot)
        properties += list(annot.keys())
    if embed_all or embed_sources:
        qs = qs.prefetch_related("org_set").annotate(
            sources=JSONBAgg(
                JSONObject(
                    # logo="org_set__logo",
                    # fullname="org_set__fullname_i18n",
                    slug="org_set__slug",
                    # name="org_set__name_i18n",
                    link="orgs_source__link",
                )
            )
        )
        properties.append("sources")
    if limit is not None:
        qs = qs[offset : offset + limit]
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


@router.get("/{slug}", response=HutSchemaDetails, exclude_unset=True, operation_id="get_hut")
@with_language_param()
def get_hut(request: HttpRequest, slug: str, lang: LanguageParam, fields: Query[FieldsParam[HutSchemaDetails]]) -> Hut:
    """Get a hut by its slug."""
    activate(lang)
    qs = Hut.objects.select_related("hut_owner").all().filter(is_active=True, is_public=True, slug=slug)
    media_url = request.build_absolute_uri(settings.MEDIA_URL)
    qs = qs.select_related("hut_type_open", "hut_type_closed", "hut_owner").annotate(
        sources=JSONBAgg(
            JSONObject(
                logo=Concat(Value(media_url), F("org_set__logo")),
                fullname="org_set__fullname_i18n",
                slug="org_set__slug",
                name="org_set__name_i18n",
                link="orgs_source__link",
            )
        )
    )
    # with override(lang):
    hut_db = qs.first()
    if hut_db is None:
        msg = f"Could not find '{slug}'."
        raise Http404(msg)
    link = reverse_lazy("admin:huts_hut_change", args=[hut_db.pk])
    hut_db.edit_link = request.build_absolute_uri(link)
    return hut_db
    # schema = HutSchemaDetails.model_validate(hut_db)
    # schema.edit_link = reverse_lazy("admin:huts_hut__change", hut_db.id)
    # return schema.model_dump()
    ## return fields.validate(list(huts_db))


#
#  @router.post("/", response=OrganizationOptional)
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

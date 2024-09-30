import typing as t
from typing import Any, List

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
from django.views.decorators.cache import cache_control
from ninja.decorators import decorate_view

from server.apps.api.query import FieldsParam, TristateEnum
from server.apps.translations import (
    LanguageParam,
    activate,
    with_language_param,
)

from ..models import Hut
from ..schemas import HutSchemaDetails, HutSchemaOptional, ImageInfoSchema
from ._router import router
from .expressions import GeoJSON

from rich import print


@router.get("huts", response=list[HutSchemaDetails], exclude_unset=True, operation_id="get_huts")
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
) -> Any:
    """Get a list with huts."""
    activate(lang)
    huts_db = Hut.objects.select_related("hut_owner").all()
    if is_modified != TristateEnum.unset:
        huts_db = huts_db.filter(is_modified=is_modified.bool)
    if is_active != TristateEnum.unset:
        huts_db = huts_db.filter(is_active=is_active.bool)
    if is_public != TristateEnum.unset:
        huts_db = huts_db.filter(is_public=is_public.bool)

    media_url = request.build_absolute_uri(settings.MEDIA_URL)
    iam_media_url = "https://res.cloudinary.com/wodore/image/upload/v1/"
    huts_db = huts_db.select_related("hut_type_open", "hut_type_closed", "hut_owner").annotate(
        sources=JSONBAgg(
            JSONObject(
                logo="org_set__logo",
                fullname="org_set__fullname_i18n",
                slug="org_set__slug",
                name="org_set__name_i18n",
                link="orgs_source__link",
            )
        ),
        images=JSONBAgg(
            JSONObject(
                image="image_set__image",
                image_url=Concat(Value(iam_media_url), F("image_set__image")),
                image_meta=JSONObject(
                    crop="image_set__image_meta__crop",
                    focal="image_set__image_meta__focal",
                    width="image_set__image_meta__width",
                    height="image_set__image_meta__height",
                ),
                caption="image_set__caption_i18n",
                license=JSONObject(
                    slug="image_set__license__slug",
                    name="image_set__license__name_i18n",
                    fullname="image_set__license__fullname_i18n",
                    description="image_set__license__description_i18n",
                    link="image_set__license__link_i18n",
                ),
                author="image_set__author",
                author_url="image_set__author_url",
                source_url="image_set__source_url",
                organization=JSONObject(
                    logo=Concat(Value(media_url), F("image_set__source_org__logo")),
                    fullname="image_set__source_org__fullname_i18n",
                    slug="image_set__source_org__slug",
                    name="image_set__source_org__name_i18n",
                    link="image_set__source_org__url",  # get link
                    # source_id="orgs_source__source_id",
                    # public="image_set__source_org__is_public",
                    # active="image_set__source_org__is_active",
                ),
                attribution=Value(""),
                # tags="image_set__tag_set",
            ),
            ordering="image_set__details__order",
        ),
        translations=JSONObject(
            description=JSONObject(
                de="description_de",
                en="description_en",
                fr="description_fr",
                it="description_it",
            ),
            name=JSONObject(
                de="name_de",
                en="name_en",
                fr="name_fr",
                it="name_it",
            ),
        ),
    )
    for hut_db in huts_db:
        if len(hut_db.sources) and hut_db.sources[0]["slug"] is None:
            hut_db.sources = []
        if len(hut_db.images) and hut_db.images[0]["image"] is None:
            hut_db.images = []
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
@decorate_view(cache_control(max_age=3600))
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
@decorate_view(cache_control(max_age=10))
def get_hut(request: HttpRequest, slug: str, lang: LanguageParam, fields: Query[FieldsParam[HutSchemaDetails]]) -> Hut:
    """Get a hut by its slug."""
    activate(lang)
    qs = Hut.objects.select_related("hut_owner").all().filter(is_active=True, is_public=True, slug=slug)
    media_url = request.build_absolute_uri(settings.MEDIA_URL)
    iam_media_url = "https://res.cloudinary.com/wodore/image/upload/v1/"
    qs = qs.select_related("hut_type_open", "hut_type_closed", "hut_owner").annotate(
        sources=JSONBAgg(
            JSONObject(
                logo=Concat(Value(media_url), F("org_set__logo")),
                fullname="org_set__fullname_i18n",
                slug="org_set__slug",
                name="org_set__name_i18n",
                link="orgs_source__link",
                source_id="orgs_source__source_id",
                public="org_set__is_public",
                active="org_set__is_active",
            ),
            ordering="org_set__order",
        ),
        images=JSONBAgg(
            JSONObject(
                image="image_set__image",
                image_url=Concat(Value(iam_media_url), F("image_set__image")),
                image_meta=JSONObject(
                    crop="image_set__image_meta__crop",
                    focal="image_set__image_meta__focal",
                    width="image_set__image_meta__width",
                    height="image_set__image_meta__height",
                ),
                caption="image_set__caption_i18n",
                license=JSONObject(
                    slug="image_set__license__slug",
                    name="image_set__license__name_i18n",
                    fullname="image_set__license__fullname_i18n",
                    description="image_set__license__description_i18n",
                    link="image_set__license__link_i18n",
                ),
                author="image_set__author",
                author_url="image_set__author_url",
                source_url="image_set__source_url",
                organization=JSONObject(
                    logo=Concat(Value(media_url), F("image_set__source_org__logo")),
                    fullname="image_set__source_org__fullname_i18n",
                    slug="image_set__source_org__slug",
                    name="image_set__source_org__name_i18n",
                    link="image_set__source_org__url",  # get link
                    # source_id="orgs_source__source_id",
                    # public="image_set__source_org__is_public",
                    # active="image_set__source_org__is_active",
                ),
                attribution=Value(""),
                # tags="image_set__tag_set",
            ),
            ordering="image_set__details__order",
        ),
        translations=JSONObject(
            description=JSONObject(
                de="description_de",
                en="description_en",
                fr="description_fr",
                it="description_it",
            ),
            name=JSONObject(
                de="name_de",
                en="name_en",
                fr="name_fr",
                it="name_it",
            ),
        ),
    )
    # with override(lang):
    hut_db = qs.first()
    ## TODO: withotu soures it has length 0 with all elements set to None
    if hut_db is None:
        msg = f"Could not find '{slug}'."
        raise Http404(msg)
    if len(hut_db.sources) and hut_db.sources[0]["slug"] is None:
        hut_db.sources = []
    if len(hut_db.images) and hut_db.images[0]["image"] is None:
        hut_db.images = []
    for img in hut_db.images:
        img_s = ImageInfoSchema(**img)
        org = img_s.organization
        if org is not None and org.slug is None:
            img["organization"] = None
            img_s.organization = None
        attribution = ""
        if img_s.license:
            attribution = f"&copy; {img_s.license.name}"
            if img_s.license.link:
                attribution = f"&copy; <a href='{img_s.license.link}'>{img_s.license.name}</a>"
        if img_s.author:
            if img_s.author_url:
                attribution += f" | <a href='{img_s.author_url}'>{img_s.author}</a>"
            else:
                attribution += f" | {img_s.author}"
        if img_s.organization:
            if img_s.organization.link:
                attribution += f" | <a href='{img_s.organization.link}'>{img_s.organization.name}</a>"
            else:
                attribution += f" | {img_s.organization.name}"
        if img_s.source_url:
            attribution += f" (<a href='{img_s.source_url}'>Original</a>)"
        attribution = attribution.strip(" |")

        img["attribution"] = attribution
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

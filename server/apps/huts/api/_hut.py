import typing as t
from typing import Any

import msgspec
from benedict import benedict
from geojson_pydantic import FeatureCollection
from ninja import Query
from ninja.decorators import decorate_view
# from rich import print

# from ninja.errors import HttpError
from django.conf import settings
from django.contrib.postgres.aggregates import JSONBAgg
from django.db.models import Case, F, Value, When
from django.db.models.functions import Coalesce, Concat, JSONObject  # , Lower
from django.http import Http404, HttpRequest, HttpResponse
from django.urls import reverse_lazy
from django.views.decorators.cache import cache_control

from server.apps.api.query import FieldsParam, TristateEnum
from enum import Enum


from server.apps.huts.schemas._hut import ImageMetaSchema
from server.apps.translations import (
    LanguageParam,
    activate,
    with_language_param,
)

from ..models import Hut
from ..schemas import (
    HutSchemaDetails,
    HutSchemaList,
    HutSearchResultSchema,
    ImageInfoSchema,
    LicenseInfoSchema,
)
from ._router import router
from .etag_utils import (
    check_etag_match,
    check_if_modified_since,
    generate_etag,
    get_last_modified_http_date,
    get_last_modified_timestamp,
    set_cache_headers,
)
from .expressions import GeoJSON


class IncludeModeEnum(str, Enum):
    """Include mode enum for search endpoint - controls level of detail."""

    no = "no"
    slug = "slug"
    all = "all"


# Search endpoint
@router.get(
    "search",
    response=list[HutSearchResultSchema],
    exclude_unset=True,
    operation_id="search_huts",
)
@decorate_view(cache_control(max_age=60))
@with_language_param("lang")
def search_huts(
    request: HttpRequest,
    response: HttpResponse,
    lang: LanguageParam,
    q: str = Query(
        ...,
        description="Search query string to match against hut names in all languages",
        example="rotond",
    ),
    offset: int = Query(0, description="Number of results to skip for pagination"),
    limit: int | None = Query(15, description="Maximum number of results to return"),
    threshold: float = Query(
        0.1,
        description="Minimum similarity score (0.0-1.0). Lower values return more results but with lower relevance. Recommended: 0.1 for fuzzy matching, 0.3 for stricter matching.",
    ),
    include_hut_type: IncludeModeEnum = Query(
        IncludeModeEnum.no,
        description="Include hut type information: 'no' excludes field, 'slug' returns type slugs only, 'all' returns full type details with icons",
    ),
    include_sources: IncludeModeEnum = Query(
        IncludeModeEnum.no,
        description="Include data sources: 'no' excludes field, 'slug' returns source slugs only, 'all' returns full source details with logos",
    ),
    include_avatar: bool = Query(
        True,
        description="Include avatar/primary photo URL in results",
    ),
) -> Any:
    """Search for huts using fuzzy text search across all language fields."""
    activate(lang)

    # Use the search manager method
    qs = Hut.objects.search(
        query=q,
        language=lang,
        threshold=threshold,
        is_active=True,
        is_public=True,
    )

    # Build annotations based on include parameters
    if include_hut_type != "no":
        qs = qs.select_related(
            "hut_type_open",
            "hut_type_closed",
            "hut_type_open__symbol_detailed",
            "hut_type_open__symbol_simple",
            "hut_type_open__symbol_mono",
            "hut_type_closed__symbol_detailed",
            "hut_type_closed__symbol_simple",
            "hut_type_closed__symbol_mono",
        )

    # Add source annotations based on include_sources parameter
    if include_sources == "slug":
        qs = qs.annotate(organization_slugs=JSONBAgg(F("org_set__slug"), distinct=True))
    elif include_sources == "all":
        qs = qs.annotate(
            sources_data=JSONBAgg(
                JSONObject(
                    slug="org_set__slug",
                    name="org_set__name_i18n",
                    fullname="org_set__fullname_i18n",
                    link="orgs_source__link",
                    logo="org_set__logo",
                    public="org_set__is_public",
                    source_id="orgs_source__source_id",
                ),
                distinct=True,
            )
        )

    # Apply limit and offset
    if limit is not None:
        qs = qs[offset : offset + limit]

    # Build simplified response
    results = []
    # Always calculate media_url for images (icons, logos, avatar)
    media_url = settings.MEDIA_URL
    if not media_url.startswith("http"):
        media_url = request.build_absolute_uri(media_url)

    for hut in qs:
        result = {
            "name": hut.name_i18n,
            "slug": hut.slug,
            "capacity": {
                "open": hut.capacity_open,
                "closed": hut.capacity_closed,
            },
            "location": hut.location,
            "elevation": hut.elevation,
            "score": hut.combined_score,
        }

        # Include hut_type based on parameter (only add field if not 'no')
        if include_hut_type == "slug":
            result["hut_type"] = {
                "open": hut.hut_type_open.slug if hut.hut_type_open else None,
                "closed": hut.hut_type_closed.slug if hut.hut_type_closed else None,
            }
        elif include_hut_type == "all":
            result["hut_type"] = {
                "open": {
                    "slug": hut.hut_type_open.slug,
                    "name": hut.hut_type_open.name_i18n,
                    "symbol": {
                        "mono": request.build_absolute_uri(
                            hut.hut_type_open.symbol_mono.svg_file.url
                        )
                        if hut.hut_type_open.symbol_mono
                        else None,
                        "detailed": request.build_absolute_uri(
                            hut.hut_type_open.symbol_detailed.svg_file.url
                        )
                        if hut.hut_type_open.symbol_detailed
                        else None,
                        "simple": request.build_absolute_uri(
                            hut.hut_type_open.symbol_simple.svg_file.url
                        )
                        if hut.hut_type_open.symbol_simple
                        else None,
                    },
                }
                if hut.hut_type_open
                else None,
                "closed": {
                    "slug": hut.hut_type_closed.slug,
                    "name": hut.hut_type_closed.name_i18n,
                    "symbol": {
                        "mono": request.build_absolute_uri(
                            hut.hut_type_closed.symbol_mono.svg_file.url
                        )
                        if hut.hut_type_closed.symbol_mono
                        else None,
                        "detailed": request.build_absolute_uri(
                            hut.hut_type_closed.symbol_detailed.svg_file.url
                        )
                        if hut.hut_type_closed.symbol_detailed
                        else None,
                        "simple": request.build_absolute_uri(
                            hut.hut_type_closed.symbol_simple.svg_file.url
                        )
                        if hut.hut_type_closed.symbol_simple
                        else None,
                    },
                }
                if hut.hut_type_closed
                else None,
            }
        # Note: when include_hut_type == "no", we don't add the field at all

        # Include sources based on parameter (only add field if not 'no')
        if include_sources == "slug":
            org_slugs = [
                slug for slug in (hut.organization_slugs or []) if slug is not None
            ]
            result["sources"] = org_slugs
        elif include_sources == "all":
            sources = []
            for src in hut.sources_data or []:
                if src.get("slug") is not None:
                    # Add full URL to logo
                    if src.get("logo"):
                        src["logo"] = f"{media_url}{src['logo']}"
                    sources.append(src)
            result["sources"] = sources
        # Note: when include_sources == "no", we don't add the field at all

        # Include avatar if requested (only add field if True)
        if include_avatar:
            if hut.photos:
                result["avatar"] = f"{media_url}{hut.photos}"
            else:
                result["avatar"] = None

        results.append(result)

    return results


@router.get(
    "huts",
    response=list[HutSchemaList],
    exclude_unset=True,
    operation_id="get_huts",
)
@with_language_param("lang")
def get_huts(  # type: ignore  # noqa: PGH003
    request: HttpRequest,
    response: HttpResponse,
    lang: LanguageParam,
    # fields: Query[FieldsParam[HutSchemaOptional]],
    offset: int = 0,
    limit: int | None = None,
    is_modified: TristateEnum = TristateEnum.unset,
    is_public: TristateEnum = TristateEnum.true,  # needs permission
    is_active: TristateEnum = TristateEnum.true,  # needs permission
    has_availability: TristateEnum = TristateEnum.unset,
) -> Any:
    """Get a list with huts."""
    activate(lang)
    huts_db = Hut.objects.select_related("hut_owner").all()

    # Generate ETag before filtering to get proper queryset for cache key
    additional_keys = [
        str(offset),
        str(limit),
        str(is_modified.value),
        str(is_public.value),
        str(is_active.value),
        str(has_availability.value),
        lang,
    ]

    etag = generate_etag(
        include_huts=True,
        include_organizations=True,  # sources are always included
        include_owners=True,  # owner is always included
        include_images=True,  # images are always included
        include_availability=False,  # availability_source_ref is part of Hut model, no need to check separately
        hut_queryset=huts_db,
        additional_keys=additional_keys,
    )

    last_modified = get_last_modified_http_date(
        include_huts=True,
        include_organizations=True,
        include_owners=True,
        include_images=True,
        include_availability=False,  # availability_source_ref is part of Hut model, no need to check separately
        hut_queryset=huts_db,
    )

    # Check if client has cached version
    # Both ETag must match AND resource must not be modified for 304 response
    if check_etag_match(request, etag) and not check_if_modified_since(
        request, last_modified
    ):
        # Return 304 Not Modified
        response.status_code = 304
        set_cache_headers(response, etag, last_modified, max_age=60)
        return response
    if is_modified != TristateEnum.unset:
        huts_db = huts_db.filter(is_modified=is_modified.bool)
    if is_active != TristateEnum.unset:
        huts_db = huts_db.filter(is_active=is_active.bool)
    if is_public != TristateEnum.unset:
        huts_db = huts_db.filter(is_public=is_public.bool)
    if has_availability != TristateEnum.unset:
        if has_availability.bool:
            # Filter for huts that have an availability source
            huts_db = huts_db.filter(availability_source_ref__isnull=False)
        else:
            # Filter for huts without an availability source
            huts_db = huts_db.filter(availability_source_ref__isnull=True)

    media_url = request.build_absolute_uri(settings.MEDIA_URL)
    iam_media_url = "https://res.cloudinary.com/wodore/image/upload/v1/"
    huts_db = huts_db.select_related(
        "hut_type_open", "hut_type_closed", "hut_owner", "availability_source_ref"
    ).annotate(
        # has_availability is True if availability_source_ref is set (hut has an availability source)
        has_availability=Case(
            When(availability_source_ref__isnull=False, then=Value(True)),
            default=Value(False),
        ),
        availability_source_ref__slug=F("availability_source_ref__slug"),
        sources=JSONBAgg(
            JSONObject(
                logo=Concat(Value(media_url), F("org_set__logo")),
                fullname="org_set__fullname_i18n",
                slug="org_set__slug",
                name="org_set__name_i18n",
                link="orgs_source__link",
                source_id="orgs_source__source_id",
                public="org_set__is_public",
            ),
            distinct=True,
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

    # Set cache headers
    set_cache_headers(response, etag, last_modified, max_age=60)

    return huts_db
    # return fields.validate(list(huts_db))


def get_json_obj(
    values: dict[str, t.Any], flat: bool = False
) -> dict[str, JSONObject | F]:
    if flat:
        return {
            k: F(str(v)) for k, v in benedict(values).flatten(separator="_").items()
        }
    new_vals = {}
    for key, value in values.items():
        new_vals[key] = (
            JSONObject(**get_json_obj(value)) if isinstance(value, dict) else value
        )
    return new_vals


@router.get("huts.geojson", response=FeatureCollection, operation_id="get_huts_geojson")
@with_language_param("lang")
def get_huts_geojson(  # type: ignore  # noqa: PGH003
    request: HttpRequest,
    response: HttpResponse,
    lang: LanguageParam,
    offset: int = 0,
    limit: int | None = None,
    has_availability: TristateEnum = TristateEnum.unset,
    # is_public: bool | None = None, # needs permission
    embed_all: bool = False,
    embed_type: bool = False,
    embed_owner: bool = False,
    embed_capacity: bool = False,
    embed_sources: bool = False,
    include_elevation: bool = False,
    include_name: bool = False,
    include_has_availability: bool = False,
    flat: bool = True,
) -> HttpResponse:
    activate(lang)
    qs = Hut.objects.filter(is_active=True, is_public=True)

    # Determine which tables are involved based on embed parameters
    include_organizations_in_etag = embed_all or embed_sources or embed_owner
    include_owners_in_etag = embed_all or embed_owner
    # Note: has_availability uses availability_source_ref which is part of Hut model,
    # so no separate availability table check needed

    # Generate ETag and Last-Modified based on involved tables
    # Include query parameters in ETag to ensure different queries get different ETags
    additional_keys = [
        str(offset),
        str(limit),
        str(has_availability.value),
        str(embed_all),
        str(embed_type),
        str(embed_owner),
        str(embed_capacity),
        str(embed_sources),
        str(include_elevation),
        str(include_name),
        str(include_has_availability),
        str(flat),
        lang,
    ]

    etag = generate_etag(
        include_huts=True,
        include_organizations=include_organizations_in_etag,
        include_owners=include_owners_in_etag,
        include_images=False,  # Images not included in geojson
        include_availability=False,  # availability_source_ref is part of Hut model
        hut_queryset=qs,
        additional_keys=additional_keys,
    )

    last_modified = get_last_modified_http_date(
        include_huts=True,
        include_organizations=include_organizations_in_etag,
        include_owners=include_owners_in_etag,
        include_images=False,
        include_availability=False,  # availability_source_ref is part of Hut model
        hut_queryset=qs,
    )

    # Check if client has cached version
    # Both ETag must match AND resource must not be modified for 304 response
    if check_etag_match(request, etag) and not check_if_modified_since(
        request, last_modified
    ):
        # Return 304 Not Modified
        response.status_code = 304
        response["ETag"] = etag
        response["Last-Modified"] = last_modified
        return response
    # if isinstance(is_public, bool):
    #     qs = qs.filter(is_public=is_public)

    # Track if has_availability annotation was added to avoid duplicate subqueries
    has_availability_annotated = False

    # Add annotation first if needed for filtering or inclusion
    if has_availability != TristateEnum.unset or embed_all or include_has_availability:
        # Select availability_source_ref to avoid extra query
        qs = qs.select_related("availability_source_ref")
        qs = qs.annotate(
            # has_availability is True if availability_source_ref is set (hut has an availability source)
            has_availability=Case(
                When(availability_source_ref__isnull=False, then=Value(True)),
                default=Value(False),
            ),
            availability_source_ref__slug=F("availability_source_ref__slug"),
        )
        has_availability_annotated = True

        # Apply filter if specified
        if has_availability != TristateEnum.unset:
            if has_availability.bool:
                qs = qs.filter(availability_source_ref__isnull=False)
            else:
                qs = qs.filter(availability_source_ref__isnull=True)

    properties = [
        "id",
        "slug",
    ]

    # Collect all select_related fields first, then apply once
    select_related_fields = []

    if embed_all or include_elevation:
        properties.append("elevation")
    if embed_all or include_name:
        properties.append("name")
    if has_availability_annotated:
        properties.append("has_availability")
    if embed_all or embed_type:
        select_related_fields.extend(["hut_type_open", "hut_type_closed"])
        annot = get_json_obj(
            flat=flat,
            values={
                "type": {
                    "open": {
                        "slug": "hut_type_open__slug",
                        "order": "hut_type_open__order",
                    },
                    "closed": {
                        "slug": "hut_type_closed__slug",
                        "order": "hut_type_closed__order",
                    },
                },
            },
        )
        qs = qs.annotate(**annot)
        properties += list(annot.keys())
    if embed_all or embed_owner:
        select_related_fields.append("hut_owner")
        annot = get_json_obj(
            flat=flat,
            values={
                "owner": {
                    "name": "hut_owner__name_i18n",
                    "slug": "hut_owner__slug",
                }
            },
        )
        qs = qs.annotate(**annot)
        properties += list(annot.keys())

    # Apply all select_related in one call for efficiency
    if select_related_fields:
        qs = qs.select_related(*select_related_fields)
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
        qs = qs.annotate(
            sources=JSONBAgg(
                JSONObject(
                    # logo="org_set__logo",
                    # fullname="org_set__fullname_i18n",
                    slug="org_set__slug",
                    # name="org_set__name_i18n",
                    link="orgs_source__link",
                    source_id="orgs_source__source_id",
                ),
                distinct=True,
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

    # Set cache headers (ETag, Last-Modified, Cache-Control)
    # With ETags, we can cache aggressively (1 year) - clients will still get fresh data
    # via 304 Not Modified responses when ETags match on every request
    set_cache_headers(response, etag, last_modified, max_age=60)

    return response


@router.get(
    "/{slug}", response=HutSchemaDetails, exclude_unset=True, operation_id="get_hut"
)
@with_language_param()
def get_hut(
    request: HttpRequest,
    response: HttpResponse,
    slug: str,
    lang: LanguageParam,
    fields: Query[FieldsParam[HutSchemaDetails]],
) -> Hut:
    """Get a hut by its slug."""
    activate(lang)
    qs = (
        Hut.objects.select_related("hut_owner")
        .all()
        .filter(is_active=True, is_public=True, slug=slug)
    )

    # Generate ETag for this specific hut
    additional_keys = [slug, lang]

    etag = generate_etag(
        include_huts=True,
        include_organizations=True,  # sources are always included
        include_owners=True,  # owner is always included
        include_images=True,  # images are always included
        include_availability=False,  # availability_source_ref is part of Hut model, no need to check separately
        hut_queryset=qs,
        additional_keys=additional_keys,
    )

    last_modified = get_last_modified_http_date(
        include_huts=True,
        include_organizations=True,
        include_owners=True,
        include_images=True,
        include_availability=False,  # availability_source_ref is part of Hut model, no need to check separately
        hut_queryset=qs,
    )

    # Check if client has cached version
    # Both ETag must match AND resource must not be modified for 304 response
    if check_etag_match(request, etag) and not check_if_modified_since(
        request, last_modified
    ):
        # Return 304 Not Modified
        response.status_code = 304
        set_cache_headers(response, etag, last_modified, max_age=15)
        return response
    media_abs_url = request.build_absolute_uri(settings.MEDIA_URL)
    # .order_by("org_set__order")
    # # TODO: too many sources, use limit for query, does not work as expected !!
    qs = qs.select_related(
        "hut_type_open", "hut_type_closed", "hut_owner", "availability_source_ref"
    ).annotate(
        # has_availability is True if availability_source_ref is set (hut has an availability source)
        has_availability=Case(
            When(availability_source_ref__isnull=False, then=Value(True)),
            default=Value(False),
        ),
        availability_source_ref__slug=F("availability_source_ref__slug"),
        sources=JSONBAgg(
            JSONObject(
                logo=Concat(Value(media_abs_url), F("org_set__logo")),
                fullname="org_set__fullname_i18n",
                slug="org_set__slug",
                name="org_set__name_i18n",
                link="orgs_source__link",
                source_id="orgs_source__source_id",
                public="org_set__is_public",
                active="org_set__is_active",
                order="org_set__order",
            ),
            # ordering="org_set__order",
            distinct=True,
        ),
        images=JSONBAgg(
            JSONObject(
                image="image_set__image",
                # image_url=Concat(Value(iam_media_url), F("image_set__image")),
                image_meta=JSONObject(
                    crop="image_set__image_meta__crop",
                    focal="image_set__image_meta__focal",
                    width="image_set__image_meta__width",
                    height="image_set__image_meta__height",
                ),
                review_status="image_set__review_status",
                caption="image_set__caption_i18n",
                license=JSONObject(
                    slug="image_set__license__slug",
                    is_active="image_set__license__is_active",
                    name=Coalesce(
                        "image_set__license__name_i18n", "image_set__license__slug"
                    ),
                    fullname=Coalesce(
                        "image_set__license__fullname_i18n",
                        "image_set__license__name_i18n",
                        "image_set__license__slug",
                    ),
                    description="image_set__license__description_i18n",
                    link="image_set__license__link_i18n",
                    no_publication="image_set__license__no_publication",
                ),
                author="image_set__author",
                author_url="image_set__author_url",
                source_url="image_set__source_url",
                organization=JSONObject(
                    logo=Concat(Value(media_abs_url), F("image_set__source_org__logo")),
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
    else:
        # ordering should be done in DB, but somehow it does not work with 'distinct'
        hut_db.sources = sorted(hut_db.sources, key=lambda x: x["order"])
    if len(hut_db.images) and hut_db.images[0]["image"] is None:
        hut_db.images = []
    updated_images = []
    for img in hut_db.images:
        # print(img)
        if img.get("review_status", "disabled") != "approved" or img.get(
            "license", {}
        ).get("no_publication", True):
            continue
        img_s = ImageInfoSchema(**img)
        org = img_s.organization
        if org is not None and org.slug is None:
            img["organization"] = None
            img_s.organization = None
        attribution = ""
        if img_s.license:
            attribution = f"&copy; {img_s.license.name}"
            if img_s.license.link:
                attribution = (
                    f"&copy; <a href='{img_s.license.link}'>{img_s.license.name}</a>"
                )
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
        updated_images.append(img)
    hut_db.images = updated_images
    if hut_db.photos:
        old_photo = ImageInfoSchema(
            image=hut_db.photos,
            image_meta=ImageMetaSchema(),
            license=LicenseInfoSchema(
                slug="copyright", name="Copyright", fullname="Copyright"
            ),
            attribution=hut_db.photos_attribution,
        )
        hut_db.images = [old_photo, *hut_db.images]
    link = reverse_lazy("admin:huts_hut_change", args=[hut_db.pk])
    hut_db.edit_link = request.build_absolute_uri(link)

    # Get modified timestamp from ETag calculation (checks all related tables)
    modified_timestamp = get_last_modified_timestamp(
        include_huts=True,
        include_organizations=True,
        include_owners=True,
        include_images=True,
        include_availability=False,
        hut_queryset=qs,
    )
    # Convert timestamp to datetime for the schema
    from datetime import datetime, timezone

    hut_db.modified = datetime.fromtimestamp(modified_timestamp, tz=timezone.utc)

    # Set cache headers
    set_cache_headers(response, etag, last_modified, max_age=15)

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

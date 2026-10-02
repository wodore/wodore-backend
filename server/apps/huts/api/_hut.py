"""Hut endpoints on dmr: search, list, GeoJSON, detail, meta, Markdown.

Route order here is load-bearing (kept explicit in ``paths`` at the
bottom): specific routes must come before the ``{slug}`` catch-all, and
``{slug}.md`` must come before ``{slug}``.
"""

import datetime
from http import HTTPStatus
from typing import Any

import pydantic
from benedict import benedict
from dmr import Path, Query, modify, validate
from dmr.headers import HeaderSpec
from dmr.metadata import ResponseSpec
from dmr.routing import external_path, path
from geojson_pydantic import FeatureCollection
from pydantic import Field

from django.conf import settings
from django.contrib.postgres.aggregates import JSONBAgg
from django.db.models import Case, F, Value, When
from django.db.models.functions import JSONObject
from django.http import Http404, HttpRequest, HttpResponse
from django.urls import reverse_lazy

from server.apps.api.controller import ApiController, cache_headers
from server.apps.api.enums import IncludeModeEnum
from server.apps.api.query import TristateEnum, dump_sparse, sparse_fields_query
from server.apps.huts.schemas._hut import ImageMetaSchema
from server.apps.translations import LanguageQuery, activate

from ..models import Hut
from ..schemas import (
    HutSchemaDetails,
    HutSchemaList,
    HutSearchResultSchema,
    ImageInfoSchema,
    LicenseInfoSchema,
    OrganizationBaseSchema,
)
from .annotations import annotate_hut_images, annotate_hut_sources
from .etag_utils import (
    cached_200,
    cached_304,
    check_etag_match,
    check_if_modified_since,
    generate_etag,
    get_last_modified_http_date,
    get_last_modified_timestamp,
)
from .expressions import GeoJSON

# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


class _HutSlug(pydantic.BaseModel):
    """Hut slug path parameter."""

    slug: str = Field(description="Hut slug")


class HutSearchQuery(LanguageQuery):
    """Query parameters for the hut search endpoint."""

    q: str = Field(
        description="Search query string to match against hut names in all languages",
        json_schema_extra={"example": "rotond"},
    )
    offset: int = Field(0, description="Number of results to skip for pagination")
    limit: int | None = Field(15, description="Maximum number of results to return")
    threshold: float = Field(
        0.1,
        description=(
            "Minimum similarity score (0.0-1.0). Lower values return more "
            "results but with lower relevance. Recommended: 0.1 for fuzzy "
            "matching, 0.3 for stricter matching."
        ),
    )
    include_hut_type: IncludeModeEnum = Field(  # type: ignore[assignment]
        IncludeModeEnum.no,
        description=(
            "Include hut type information: 'no' excludes field, 'slug' "
            "returns type slugs only, all returns full type details "
            "with icons"
        ),
    )
    include_sources: IncludeModeEnum = Field(  # type: ignore[assignment]
        IncludeModeEnum.no,
        description=(
            "Include data sources: 'no' excludes field, 'slug' returns "
            "source slugs only, all returns full source details with logos"
        ),
    )
    include_avatar: bool = Field(
        True,
        description="Include avatar/primary photo URL in results",
    )


def _hut_type_symbol_block(request: HttpRequest, hut_type) -> dict:
    return {
        "mono": request.build_absolute_uri(hut_type.symbol_mono.svg_file.url)
        if hut_type.symbol_mono
        else None,
        "detailed": request.build_absolute_uri(hut_type.symbol_detailed.svg_file.url)
        if hut_type.symbol_detailed
        else None,
        "simple": request.build_absolute_uri(hut_type.symbol_simple.svg_file.url)
        if hut_type.symbol_simple
        else None,
    }


_CACHE_HEADER_SPECS = {
    "ETag": HeaderSpec(description="Content hash (API-version keyed)"),
    "Last-Modified": HeaderSpec(description="Last modification date"),
    "Cache-Control": HeaderSpec(description="Caching policy"),
}


class HutSearchController(ApiController):
    """Fuzzy hut search across all language fields."""

    @modify(
        operation_id="search_huts",
        headers=cache_headers(60),
    )
    def get(self, parsed_query: Query[HutSearchQuery]) -> list[dict]:
        """Search huts.

        Fuzzy text search across all language fields."""
        request = self.request
        query = parsed_query
        activate(query.lang)

        qs = Hut.objects.search(
            query=query.q,
            language=query.lang,
            threshold=query.threshold,
            is_active=True,
            is_public=True,
        )

        if query.include_hut_type != "no":
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

        if query.include_sources == "slug":
            qs = qs.annotate(
                organization_slugs=JSONBAgg(F("org_set__slug"), distinct=True)
            )
        elif query.include_sources == "all":
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

        if query.limit is not None:
            qs = qs[query.offset : query.offset + query.limit]

        results = []
        media_url = settings.MEDIA_URL
        if not media_url.startswith("http"):
            media_url = request.build_absolute_uri(media_url)

        for hut in qs:
            result = {
                "name": hut.name_i18n,  # noqa: WPS308  # modeltranslation
                "slug": hut.slug,
                "capacity": {
                    "open": hut.capacity_open,
                    "closed": hut.capacity_closed,
                },
                "location": hut.location,
                "elevation": hut.elevation,
                "score": hut.combined_score,
            }

            if query.include_hut_type == "slug":
                result["hut_type"] = {
                    "open": hut.hut_type_open.slug if hut.hut_type_open else None,
                    "closed": hut.hut_type_closed.slug if hut.hut_type_closed else None,
                }
            elif query.include_hut_type == "all":
                result["hut_type"] = {
                    "open": {
                        "slug": hut.hut_type_open.slug,
                        "name": hut.hut_type_open.name_i18n,  # noqa: WPS308
                        "color": hut.hut_type_open.color,
                        "symbol": _hut_type_symbol_block(request, hut.hut_type_open),
                    }
                    if hut.hut_type_open
                    else None,
                    "closed": {
                        "slug": hut.hut_type_closed.slug,
                        "name": hut.hut_type_closed.name_i18n,  # noqa: WPS308
                        "color": hut.hut_type_closed.color,
                        "symbol": _hut_type_symbol_block(request, hut.hut_type_closed),
                    }
                    if hut.hut_type_closed
                    else None,
                }

            if query.include_sources == "slug":
                org_slugs = [
                    slug for slug in (hut.organization_slugs or []) if slug is not None
                ]
                result["sources"] = org_slugs
            elif query.include_sources == "all":
                sources = []
                for src in hut.sources_data or []:
                    if src.get("slug") is not None:
                        if src.get("logo"):
                            src["logo"] = f"{media_url}{src['logo']}"
                        sources.append(src)
                result["sources"] = sources

            if query.include_avatar:
                if hut.photos:
                    result["avatar"] = f"{media_url}{hut.photos}"
                else:
                    result["avatar"] = None

            results.append(result)

        return [
            HutSearchResultSchema(**result).model_dump(exclude_unset=True)
            for result in results
        ]


# ---------------------------------------------------------------------------
# huts list (ETag + Last-Modified)
# ---------------------------------------------------------------------------


class HutListQuery(LanguageQuery):
    """Query parameters for the hut list endpoint."""

    offset: int = Field(0, description="Pagination offset")
    limit: int | None = Field(None, description="Maximum number of huts")
    is_modified: TristateEnum = Field(  # type: ignore[assignment]
        TristateEnum.unset, description="Filter modified huts"
    )
    is_public: TristateEnum = Field(  # type: ignore[assignment]
        TristateEnum.true, description="Filter public huts (needs permission)"
    )
    is_active: TristateEnum = Field(  # type: ignore[assignment]
        TristateEnum.true, description="Filter active huts (needs permission)"
    )
    has_availability: TristateEnum = Field(  # type: ignore[assignment]
        TristateEnum.unset, description="Filter huts with availability source"
    )


class HutsController(ApiController):
    """All huts (annotated, ETag-cached)."""

    @validate(
        ResponseSpec(
            list[HutSchemaList],
            status_code=HTTPStatus.OK,
            headers=_CACHE_HEADER_SPECS,
        ),
        ResponseSpec(
            None,
            status_code=HTTPStatus.NOT_MODIFIED,
            headers=_CACHE_HEADER_SPECS,
        ),
        description="Hut list (ETag-cached).",
        operation_id="get_huts",
        exclude_validate_responses={HTTPStatus.NOT_MODIFIED},
    )
    def get(self, parsed_query: Query[HutListQuery]) -> HttpResponse:
        """List huts."""
        request = self.request
        query = parsed_query
        activate(query.lang)
        huts_db = Hut.objects.select_related("hut_owner").all()

        additional_keys = [
            str(query.offset),
            str(query.limit),
            str(query.is_modified.value),
            str(query.is_public.value),
            str(query.is_active.value),
            str(query.has_availability.value),
            query.lang,
        ]
        from server.apps.apiversions.transforms import version_cache_key

        additional_keys.append(version_cache_key(request))

        etag = generate_etag(
            include_huts=True,
            include_categories=True,  # hut types/availability statuses are embedded
            include_organizations=True,  # sources are always included
            include_owners=True,  # owner is always included
            include_images=True,  # images are always included
            include_availability=False,  # availability_source_ref is part of Hut
            hut_queryset=huts_db,
            additional_keys=additional_keys,
        )

        last_modified = get_last_modified_http_date(
            include_huts=True,
            include_organizations=True,
            include_owners=True,
            include_images=True,
            include_availability=False,
            hut_queryset=huts_db,
        )

        if check_etag_match(request, etag) and not check_if_modified_since(
            request, last_modified
        ):
            return cached_304(self, etag, last_modified, max_age=60)

        if query.is_modified != TristateEnum.unset:
            huts_db = huts_db.filter(is_modified=query.is_modified.bool)
        if query.is_active != TristateEnum.unset:
            huts_db = huts_db.filter(is_active=query.is_active.bool)
        if query.is_public != TristateEnum.unset:
            huts_db = huts_db.filter(is_public=query.is_public.bool)
        if query.has_availability != TristateEnum.unset:
            if query.has_availability.bool:
                huts_db = huts_db.filter(availability_source_ref__isnull=False)
            else:
                huts_db = huts_db.filter(availability_source_ref__isnull=True)

        media_url = request.build_absolute_uri(settings.MEDIA_URL)
        iam_media_url = "https://res.cloudinary.com/wodore/image/upload/v1/"
        huts_db = huts_db.select_related(
            "hut_type_open", "hut_type_closed", "hut_owner", "availability_source_ref"
        ).annotate(
            has_availability=Case(
                When(availability_source_ref__isnull=False, then=Value(True)),
                default=Value(False),
            ),
            availability_source_ref__slug=F("availability_source_ref__slug"),
            sources=annotate_hut_sources(media_url=media_url),
            images=annotate_hut_images(media_url=iam_media_url),
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
        if query.limit is not None:
            huts_db = huts_db[query.offset : query.offset + query.limit]

        validated = [
            HutSchemaList.model_validate(hut, context={"request": request})
            for hut in huts_db
        ]
        return cached_200(self, validated, etag, last_modified, max_age=60)


# ---------------------------------------------------------------------------
# huts.geojson
# ---------------------------------------------------------------------------


def get_json_obj(
    values: dict[str, Any], flat: bool = False
) -> dict[str, JSONObject | F]:
    if flat:
        return {  # pyright: ignore[reportReturnType]  # benedict key typing
            k: F(str(v)) for k, v in benedict(values).flatten(separator="_").items()
        }
    new_vals = {}
    for key, value in values.items():
        new_vals[key] = (
            JSONObject(**get_json_obj(value)) if isinstance(value, dict) else value
        )
    return new_vals


class HutGeojsonQuery(LanguageQuery):
    """Query parameters for the huts GeoJSON endpoint."""

    offset: int = Field(0, description="Pagination offset")
    limit: int | None = Field(None, description="Maximum number of huts")
    has_availability: TristateEnum = Field(  # type: ignore[assignment]
        TristateEnum.unset, description="Filter huts with availability source"
    )
    embed_all: bool = Field(False, description="Embed all optional blocks")
    embed_type: bool = Field(False, description="Embed hut types")
    embed_owner: bool = Field(False, description="Embed owner")
    embed_capacity: bool = Field(False, description="Embed capacities")
    embed_sources: bool = Field(False, description="Embed sources")
    include_elevation: bool = Field(False, description="Include elevation")
    include_name: bool = Field(False, description="Include name")
    include_has_availability: bool = Field(
        False, description="Include has_availability flag"
    )
    flat: bool = Field(True, description="Flatten embedded blocks")


class HutsGeojsonController(ApiController):
    """All public huts as a GeoJSON FeatureCollection."""

    @validate(
        ResponseSpec(
            FeatureCollection,
            status_code=HTTPStatus.OK,
            headers=_CACHE_HEADER_SPECS,
        ),
        ResponseSpec(
            None,
            status_code=HTTPStatus.NOT_MODIFIED,
            headers=_CACHE_HEADER_SPECS,
        ),
        description="Huts as GeoJSON (ETag-cached).",
        operation_id="get_huts_geojson",
        exclude_validate_responses={HTTPStatus.NOT_MODIFIED},
    )
    def get(self, parsed_query: Query[HutGeojsonQuery]) -> HttpResponse:
        """Get huts as GeoJSON.

        Properties controlled by embed/include parameters."""
        request = self.request
        query = parsed_query
        activate(query.lang)
        qs = Hut.objects.filter(is_active=True, is_public=True)

        include_organizations_in_etag = (
            query.embed_all or query.embed_sources or query.embed_owner
        )
        include_owners_in_etag = query.embed_all or query.embed_owner

        from server.apps.apiversions.transforms import version_cache_key

        additional_keys = [
            str(query.offset),
            str(query.limit),
            str(query.has_availability.value),
            str(query.embed_all),
            str(query.embed_type),
            str(query.embed_owner),
            str(query.embed_capacity),
            str(query.embed_sources),
            str(query.include_elevation),
            str(query.include_name),
            str(query.include_has_availability),
            str(query.flat),
            query.lang,
            version_cache_key(request),
        ]

        etag = generate_etag(
            include_huts=True,
            include_categories=True,
            include_organizations=include_organizations_in_etag,
            include_owners=include_owners_in_etag,
            include_images=False,
            include_availability=False,
            hut_queryset=qs,
            additional_keys=additional_keys,
        )

        last_modified = get_last_modified_http_date(
            include_huts=True,
            include_organizations=include_organizations_in_etag,
            include_owners=include_owners_in_etag,
            include_images=False,
            include_availability=False,
            hut_queryset=qs,
        )

        if check_etag_match(request, etag) and not check_if_modified_since(
            request, last_modified
        ):
            return cached_304(self, etag, last_modified, max_age=60)

        has_availability_annotated = False
        if (
            query.has_availability != TristateEnum.unset
            or query.embed_all
            or query.include_has_availability
        ):
            qs = qs.select_related("availability_source_ref")
            qs = qs.annotate(
                has_availability=Case(
                    When(availability_source_ref__isnull=False, then=Value(True)),
                    default=Value(False),
                ),
                availability_source_ref__slug=F("availability_source_ref__slug"),
            )
            has_availability_annotated = True

            if query.has_availability != TristateEnum.unset:
                if query.has_availability.bool:
                    qs = qs.filter(availability_source_ref__isnull=False)
                else:
                    qs = qs.filter(availability_source_ref__isnull=True)

        properties = [
            "id",
            "slug",
        ]

        select_related_fields = []

        if query.embed_all or query.include_elevation:
            properties.append("elevation")
        if query.embed_all or query.include_name:
            properties.append("name")
        if has_availability_annotated:
            properties.append("has_availability")
        if query.embed_all or query.embed_type:
            select_related_fields.extend(["hut_type_open", "hut_type_closed"])
            annot = get_json_obj(
                flat=query.flat,
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
        if query.embed_all or query.embed_owner:
            select_related_fields.append("hut_owner")
            annot = get_json_obj(
                flat=query.flat,
                values={
                    "owner": {
                        "name": "hut_owner__name_i18n",
                        "slug": "hut_owner__slug",
                    }
                },
            )
            qs = qs.annotate(**annot)
            properties += list(annot.keys())

        if select_related_fields:
            qs = qs.select_related(*select_related_fields)
        if query.embed_all or query.embed_capacity:
            annot = get_json_obj(
                flat=query.flat,
                values={
                    "capacity": {
                        "if_open": "capacity_open",
                        "if_closed": "capacity_closed",
                    }
                },
            )
            qs = qs.annotate(**annot)
            properties += list(annot.keys())
        if query.embed_all or query.embed_sources:
            qs = qs.annotate(
                sources=JSONBAgg(
                    JSONObject(
                        slug="org_set__slug",
                        link="orgs_source__link",
                        source_id="orgs_source__source_id",
                    ),
                    distinct=True,
                )
            )
            properties.append("sources")
        if query.limit is not None:
            qs = qs[query.offset : query.offset + query.limit]

        geojson = qs.aggregate(
            GeoJSON(
                geom_field="location",
                fields=properties,
                decimals=5,
            ),
        )["geojson"]
        # Version downgrades are applied uniformly by the API-version
        # middleware for every JSON response.
        return cached_200(self, geojson, etag, last_modified, max_age=60)


# ---------------------------------------------------------------------------
# hut detail
# ---------------------------------------------------------------------------


HutDetailFields = sparse_fields_query(
    huts=HutSchemaDetails,
    sources=OrganizationBaseSchema,
    images=ImageInfoSchema,
)


class HutDetailQuery(LanguageQuery, HutDetailFields):
    """Query parameters for the hut detail endpoint."""


class HutDetailController(ApiController):
    """A single hut by slug (full detail, ETag-cached)."""

    @validate(
        ResponseSpec(
            HutSchemaDetails,
            status_code=HTTPStatus.OK,
            headers=_CACHE_HEADER_SPECS,
        ),
        ResponseSpec(
            None,
            status_code=HTTPStatus.NOT_MODIFIED,
            headers=_CACHE_HEADER_SPECS,
        ),
        description="Hut detail (ETag-cached).",
        operation_id="get_hut",
        exclude_validate_responses={HTTPStatus.NOT_MODIFIED},
    )
    def get(
        self,
        parsed_path: Path[_HutSlug],
        parsed_query: Query[HutDetailQuery],
    ) -> HttpResponse:
        """Get a hut."""
        request = self.request
        slug = parsed_path.slug
        lang = request.GET.get("lang", "de")
        activate(lang)

        # Count the visit (best-effort, async — separate lightweight query
        # so it doesn't interfere with the main select_related/only chain).
        from server.apps.visits.models import record_visit

        visit_hut = (
            Hut.objects.filter(is_active=True, is_public=True, slug=slug)
            .only("id")
            .first()
        )
        if visit_hut is not None:
            record_visit(request, visit_hut)

        qs = (
            Hut.objects.select_related("hut_owner")
            .all()
            .filter(is_active=True, is_public=True, slug=slug)
        )

        from server.apps.apiversions.transforms import version_cache_key

        additional_keys = [slug, lang, version_cache_key(request)]

        etag = generate_etag(
            include_huts=True,
            include_categories=True,
            include_organizations=True,
            include_owners=True,
            include_images=True,
            include_availability=False,
            hut_queryset=qs,
            additional_keys=additional_keys,
        )

        last_modified = get_last_modified_http_date(
            include_huts=True,
            include_organizations=True,
            include_owners=True,
            include_images=True,
            include_availability=False,
            hut_queryset=qs,
        )

        if check_etag_match(request, etag) and not check_if_modified_since(
            request, last_modified
        ):
            return cached_304(self, etag, last_modified, max_age=60)

        media_abs_url = request.build_absolute_uri(settings.MEDIA_URL)
        qs = qs.select_related(
            "hut_type_open", "hut_type_closed", "hut_owner", "availability_source_ref"
        ).annotate(
            has_availability=Case(
                When(availability_source_ref__isnull=False, then=Value(True)),
                default=Value(False),
            ),
            availability_source_ref__slug=F("availability_source_ref__slug"),
            sources=annotate_hut_sources(media_url=media_abs_url, detail=True),
            images=annotate_hut_images(detail=True),
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
        hut_db = qs.first()
        if hut_db is None:
            msg = f"Could not find '{slug}'."
            raise Http404(msg)
        if len(hut_db.sources) and hut_db.sources[0]["slug"] is None:
            hut_db.sources = []
        else:
            # ordering should be done in DB, but somehow it does not work
            # with 'distinct'
            hut_db.sources = sorted(hut_db.sources, key=lambda x: x["order"])
        if len(hut_db.images) and hut_db.images[0]["image"] is None:
            hut_db.images = []
        updated_images = []
        for img in hut_db.images:
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
                if img_s.license.url:
                    attribution = (
                        f"&copy; <a href='{img_s.license.url}'>{img_s.license.name}</a>"
                    )
            if img_s.author:
                if img_s.author_url:
                    attribution += f" | <a href='{img_s.author_url}'>{img_s.author}</a>"
                else:
                    attribution += f" | {img_s.author}"
            if img_s.organization:
                if img_s.organization.url:
                    attribution += (
                        f" | <a href='{img_s.organization.url}'>"
                        f"{img_s.organization.name}</a>"
                    )
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
            hut_db.images = [old_photo.model_dump(), *hut_db.images]
        link = reverse_lazy("admin:huts_hut_change", args=[hut_db.pk])
        hut_db.edit_link = request.build_absolute_uri(link)  # pyright: ignore[reportAttributeAccessIssue]

        # Get modified timestamp from ETag calculation
        modified_timestamp = get_last_modified_timestamp(
            include_huts=True,
            include_organizations=True,
            include_owners=True,
            include_images=True,
            include_availability=False,
            hut_queryset=qs,
        )
        hut_db.modified = datetime.datetime.fromtimestamp(
            modified_timestamp, tz=datetime.timezone.utc
        )

        data = dump_sparse(
            HutSchemaDetails,
            hut_db,
            parsed_query,
            "huts",
            default_include="__all__",
            context={"request": request},
        )
        return cached_200(self, data, etag, last_modified, max_age=15)


# ---------------------------------------------------------------------------
# Route assembly. Order is load-bearing:
# availability (from the availability app) and the other specific routes
# come first — '{slug}' LAST, with '{slug}.md' just before it.
# ---------------------------------------------------------------------------

from server.apps.availability.api import (
    paths as availability_paths,  # circular-safe
)

from ._booking import paths as booking_paths
from ._hut_markdown import get_hut_markdown
from ._hut_meta import paths as meta_paths

paths: list[Any] = [
    *availability_paths,
    path("search", HutSearchController.as_view(), name="search_huts"),
    *meta_paths,
    *booking_paths,
    path("huts", HutsController.as_view(), name="get_huts"),
    path("huts.geojson", HutsGeojsonController.as_view(), name="get_huts_geojson"),
    # '{slug}.md' must register BEFORE the catch-all '{slug}'
    external_path(
        "<str:slug>.md",
        get_hut_markdown,
        openapi=None,
        name="get_hut_markdown",
    ),
    path("<str:slug>", HutDetailController.as_view(), name="get_hut"),
]

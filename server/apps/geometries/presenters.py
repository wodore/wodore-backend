"""Shared GeoPlace presenters: query filters, annotations, result building.

Extracted from ``api.py`` so the search/nearby/amenity controllers share
one implementation of type filtering, source annotation and the
place-dict projection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.db.models import QuerySet

if TYPE_CHECKING:
    from django.http import HttpRequest

    from .models import GeoPlace


def apply_type_filters(
    queryset: QuerySet[GeoPlace],
    types: list[str] | None,
    categories: list[str] | None,
) -> QuerySet[GeoPlace]:
    if categories:
        queryset = queryset.filter(categories__parent__slug__in=categories)
    if types:
        from django.db.models import Q

        type_conditions = Q()
        for type_slug in types:
            if "." in type_slug:
                parent_slug, child_slug = type_slug.split(".", 1)
                type_conditions |= Q(
                    categories__parent__slug=parent_slug, categories__slug=child_slug
                )
            else:
                # Could be either parent or child category
                type_conditions |= Q(categories__slug=type_slug) | Q(
                    categories__parent__slug=type_slug
                )
        queryset = queryset.filter(type_conditions)
    if categories or types:
        queryset = queryset.distinct()
    return queryset


def prefetch_categories(queryset: QuerySet[GeoPlace]) -> QuerySet[GeoPlace]:
    return queryset.prefetch_related(
        "categories",
        "categories__parent",
        "categories__symbol_color",
        "categories__symbol_primitive",
        "categories__symbol_mono",
    )


def annotate_sources(queryset: QuerySet[GeoPlace]) -> QuerySet[GeoPlace]:
    from django.contrib.postgres.aggregates import JSONBAgg
    from django.db.models.functions import JSONObject

    # Always produce the full shape — narrowing is projection\'s job
    return queryset.annotate(
        sources_data=JSONBAgg(
            JSONObject(
                slug="source_set__slug",
                name="source_set__name_i18n",
                logo="source_set__logo",
                source_id="source_associations__source_id",
            ),
            distinct=True,
        )
    )
    return queryset


def build_categories_data(
    place: GeoPlace, request: HttpRequest
) -> list[dict[str, Any]]:
    from server.apps.symbols.utils import resolve_symbol_urls

    categories_data = []
    for category in place.categories.all():
        category_data: dict[str, Any] = {
            "slug": category.slug,
            "name": category.name_i18n,  # noqa: WPS308  # modeltranslation
            "description": category.description_i18n,  # noqa: WPS308
        }
        symbol_data = resolve_symbol_urls(category, {"request": request})
        if symbol_data:
            category_data["symbol"] = symbol_data
        categories_data.append(category_data)
    return categories_data


def build_sources(result: dict[str, Any], place: GeoPlace, media_url: str) -> None:
    from server.apps.organizations.schema import (
        OrganizationSourceIdDetailSchema,
    )

    sources = []
    # sources_data is a queryset annotation (annotate_sources), not a model
    # field — django-stubs cannot model .annotate() attributes.
    for src in place.sources_data or []:  # type: ignore  # annotated attr (JSONBAgg sources_data), not a GeoPlace field
        if src.get("slug") is not None:
            org_data = {
                "slug": src["slug"],
                "name": src.get("name"),
                "logo": (f"{media_url}{src['logo']}" if src.get("logo") else None),
            }
            source_item = OrganizationSourceIdDetailSchema(
                source=org_data,  # type: ignore[arg-type]
                source_id=src.get("source_id"),
            )
            sources.append(
                source_item.dict(exclude_unset=True, exclude={"source": {"logo"}})
            )
    if sources:
        result["sources"] = sources


def base_result(place: GeoPlace, media_url: str) -> dict[str, Any]:
    return {
        "name": place.name_i18n,  # noqa: WPS308  # modeltranslation
        "country_code": str(place.country_code) if place.country_code else None,
        "slug": place.slug,
        "elevation": place.elevation,
        "importance": place.importance,
        "location": {
            "lat": place.location.y if place.location else None,
            "lon": place.location.x if place.location else None,
        },
    }


def build_amenity_detail(place: GeoPlace) -> dict[str, Any] | None:
    """Serialize the place's ``AmenityDetail`` into the wire block.

    Returns ``None`` when the place has no detail row (callers seed
    the member anyway so it stays a valid field-selection name) —
    the amenity endpoint's former crash-prone inline mapping, moved
    here once (place-detail-endpoint). Requires ``select_related``
    when called (cached ``None`` on absent rows, no exception).
    """
    detail = getattr(place, "amenity_detail", None)  # plugin-less inference gap
    if detail is None:
        return None
    # Websites/links live at the place level (external links), overflow
    # data on GeoPlace.extra — neither is part of this block.
    return {
        "operating_status": detail.operating_status,
        "opening_months": detail.opening_months or {},
        "opening_hours": detail.opening_hours or {},
        "phones": detail.phones or [],
    }

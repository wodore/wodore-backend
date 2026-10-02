"""Shared GeoPlace presenters: query filters, annotations, result building.

Extracted from ``api.py`` so the search/nearby/amenity controllers share
one implementation of type filtering, source annotation and the
place-dict projection.
"""

from server.apps.api.enums import IncludeModeEnum


def apply_type_filters(queryset, types, categories):
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


def prefetch_categories(queryset):
    return queryset.prefetch_related(
        "categories",
        "categories__parent",
        "categories__symbol_detailed",
        "categories__symbol_simple",
        "categories__symbol_mono",
    )


def annotate_sources(queryset, include_sources: IncludeModeEnum):
    from django.contrib.postgres.aggregates import JSONBAgg
    from django.db.models import F
    from django.db.models.functions import JSONObject

    if include_sources == IncludeModeEnum.slug:
        return queryset.annotate(
            source_slugs=JSONBAgg(F("source_set__slug"), distinct=True),
            source_ids=JSONBAgg(F("source_associations__source_id"), distinct=True),
        )
    if include_sources == IncludeModeEnum.all:
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


def build_categories_data(place, request):
    from server.apps.symbols.utils import resolve_symbol_urls

    categories_data = []
    for category in place.categories.all():
        category_data = {
            "slug": category.slug,
            "name": category.name_i18n,  # noqa: WPS308  # modeltranslation
            "description": category.description_i18n,  # noqa: WPS308
        }
        symbol_data = resolve_symbol_urls(category, {"request": request})
        if symbol_data:
            category_data["symbol"] = symbol_data
        categories_data.append(category_data)
    return categories_data


def build_sources(result: dict, place, media_url: str, include_sources) -> None:
    from server.apps.organizations.schema import (
        OrganizationSourceIdDetailSchema,
        OrganizationSourceIdSlugSchema,
    )

    if include_sources == IncludeModeEnum.slug:
        slugs = [slug for slug in (place.source_slugs or []) if slug is not None]
        ids = [sid for sid in (place.source_ids or []) if sid is not None]
        sources_list = []
        for i, slug in enumerate(slugs):
            source_item = OrganizationSourceIdSlugSchema(
                source=slug, source_id=ids[i] if i < len(ids) and ids[i] else None
            )
            sources_list.append(source_item.dict(exclude_unset=True))
        if sources_list:
            result["sources"] = sources_list
    elif include_sources == IncludeModeEnum.all:
        sources = []
        for src in place.sources_data or []:
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


def base_result(place, media_url: str) -> dict:
    return {
        "name": place.name_i18n,  # noqa: WPS308  # modeltranslation
        "country_code": str(place.country_code) if place.country_code else None,
        "id": place.id,
        "elevation": place.elevation,
        "importance": place.importance,
        "location": {
            "lat": place.location.y if place.location else None,
            "lon": place.location.x if place.location else None,
        },
    }

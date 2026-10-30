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
        # Association rows carry the classifier/extra attributes
        # (geoplace-capacity-and-types-via-categories) — build_categories_data
        # maps them onto the category entries.
        "category_associations__classifier",
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

    # Association-level attributes (classifier/extra) keyed by category
    # id — prefetched by prefetch_categories (reverse through-model
    # accessor: plugin-less inference gap).
    associations = {
        association.category_id: association
        for association in place.category_associations.all()  # type: ignore  # reverse through-model accessor
    }

    categories_data = []
    for category in place.categories.all():
        association = associations.get(category.pk)
        category_data: dict[str, Any] = {
            "slug": category.slug,
            "name": category.name_i18n,  # noqa: WPS308  # modeltranslation
            "description": category.description_i18n,  # noqa: WPS308
            # season classification (season.* identifier) and typed
            # per-association attributes, when set
            "classifier": (
                association.classifier.identifier
                if association and association.classifier
                else None
            ),
            "extra": (association.extra or {}) if association else {},
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
    # sources_data is a queryset annotation (annotate_sources), not a
    # model field — django-stubs cannot model .annotate() attributes. The
    # getattr keeps nearby-without-sources working (annotation only applied
    # when the field is selected).
    for src in getattr(place, "sources_data", None) or []:
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
        # Super-root identifier (map.amenity / map.admin / map.natural /
        # none) — the pin-tier discriminator map previews key on
        # (read-performance follow-up: preview selects exactly this)
        "domain": place.domain,
        "location": {
            "lat": place.location.y if place.location else None,
            "lon": place.location.x if place.location else None,
        },
    }


def build_amenity_detail(place: GeoPlace) -> dict[str, Any] | None:
    """Serialize the place's amenity block into the wire shape.

    Served from the new homes (geoplace-kinds-operations-graph task
    4.1): ``opening_hours`` from the standard-mode ``GeoPlaceOperation``
    row, ``opening_months`` from ``GeoPlaceSeasonality`` (fuzzy →
    share round-trip), ``operating_status`` defaults to ``open``
    (the uniform constant the data carried — wire shape preserved).
    Returns ``None`` when the place has no operation or seasonality
    data (callers seed the member anyway so it stays a valid
    field-selection name).
    """
    from .models import Month

    operation = (
        place.operations.filter(mode__slug="standard")  # type: ignore  # reverse FK: plugin-less inference gap
        .only("opening_hours")
        .first()
    )
    seasonality = getattr(place, "seasonality", None)  # plugin-less inference gap

    if operation is None and seasonality is None:
        return None

    # fuzzy vocabulary round-trip (share → fuzzy labels, wire shape)
    share_to_fuzzy = {100: "yes", 75: "yesish", 50: "maybe", 25: "noish", 0: "no"}
    month_names = [
        "jan",
        "feb",
        "mar",
        "apr",
        "may",
        "jun",
        "jul",
        "aug",
        "sep",
        "oct",
        "nov",
        "dec",
    ]
    opening_months: dict[str, str] = {}
    if seasonality is not None:
        for month in Month:
            share = getattr(seasonality, f"month_{month.value:02d}")
            if share is not None:
                opening_months[month_names[month.value - 1]] = share_to_fuzzy.get(
                    share, "maybe"
                )

    return {
        "operating_status": "open",  # uniform constant, wire shape preserved
        "opening_months": opening_months,
        "opening_hours": (operation.opening_hours if operation else {}) or {},
    }


def prefetch_links(queryset: QuerySet[GeoPlace]) -> QuerySet[GeoPlace]:
    """Prefetch public, review-done external links with kind + symbols."""
    from django.db.models import Prefetch

    from .models import GeoPlaceExternalLink

    return queryset.prefetch_related(
        Prefetch(
            "link_associations",
            queryset=GeoPlaceExternalLink.objects.filter(
                external_link__is_active=True,
                external_link__is_public=True,
                external_link__review_status="done",
            )
            .select_related(
                "external_link__uri_kind",
                "external_link__uri_kind__symbol_color",
                "external_link__uri_kind__symbol_mono",
            )
            .order_by("order"),
        )
    )


def build_links_data(place: GeoPlace, request: HttpRequest) -> list[dict[str, Any]]:
    """Serialize the place's links as ``[{uri, url, label, symbol}]``.

    Mirrors ``build_parties_data``: ``uri`` is the URI-kind identifier
    (e.g. ``uri.phone``), ``symbol`` the kind's resolved color/mono
    URLs (external-link-uris).
    """
    from server.apps.symbols.utils import resolve_symbol_urls

    out: list[dict[str, Any]] = []
    # link_associations is the reverse through-model accessor
    # (GeoPlaceExternalLink.geo_place related_name) — plugin-less
    # inference gap, same class as amenity_detail/party_associations.
    for association in place.link_associations.all():  # type: ignore  # reverse through-model accessor
        link = association.external_link
        kind = link.uri_kind
        if kind is None:
            continue  # not expected after the backfill; defensive
        item: dict[str, Any] = {
            "uri": kind.identifier or "uri.website",
            "url": link.url_i18n,
            "label": link.label_i18n or None,
        }
        symbol = resolve_symbol_urls(kind, {"request": request})
        if symbol:
            item["symbol"] = symbol
        out.append(item)
    return out


def prefetch_parties(queryset: QuerySet[GeoPlace]) -> QuerySet[GeoPlace]:
    """Prefetch role-classified party associations (links + symbols)."""
    return queryset.prefetch_related(
        "party_associations__role",
        "party_associations__party__symbol_color",
        "party_associations__party__symbol_mono",
        "party_associations__party__link_associations__external_link",
    )


def build_parties_data(place: GeoPlace, request: HttpRequest) -> list[dict[str, Any]]:
    """Public party payload per place: ``[{role, slug, name, links, symbol}]``.

    Skips inactive/non-public parties (public API surface). Callers
    prefetch via :func:`prefetch_parties`.
    """
    from server.apps.symbols.utils import resolve_symbol_urls

    parties = []
    for assoc in place.party_associations.all():  # type: ignore  # reverse FK: plugin-less inference gap  # prefetched by caller
        party = assoc.party
        if not (party.is_active and party.is_public):
            continue
        parties.append(
            {
                "role": assoc.role.identifier,
                "slug": party.slug,
                "name": party.name_i18n,  # noqa: WPS308  # modeltranslation
                "links": [
                    {
                        "url": link.external_link.url,
                        "label": link.external_link.label_i18n,  # noqa: WPS308
                    }
                    for link in party.link_associations.all()
                ],
                "symbol": resolve_symbol_urls(party, {"request": request}),
            }
        )
    return parties

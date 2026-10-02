"""SEO/LLM surface for places: lean meta + Markdown documents (dmr).

Mirrors the hut surface (``server/apps/huts/api/_hut_meta.py`` and
``_hut_markdown.py``) for ``GeoPlace``:

* ``/v1/geo/places/{slug}/meta`` — minimal contract for edge meta-tag
  injection (frontend route TBD; see ``PLACE_URL_PATTERN``)
* ``/v1/geo/places/{slug}.md`` — self-contained Markdown document

GeoPlace texts are stored per place (``main_language``), not per-active
language like huts — the endpoints serve the stored text as-is.
"""

import pydantic
from dmr import Path, Query, modify
from dmr.routing import external_path, path
from pydantic import Field

from django.conf import settings
from django.http import Http404, HttpRequest, HttpResponse

from server.apps.api.controller import ApiController, cache_headers
from server.apps.images.models import Image
from server.apps.images.og import og_map_card_url, og_photo_url, photo_source

from .models import GeoPlace, GeoPlaceImageAssociation

CACHE_TTL = 60 * 60

# Endonym labels for the language variant links in the Markdown footer.
_LANGUAGE_LABELS = {
    "de": "Deutsch",
    "en": "English",
    "fr": "Français",
    "it": "Italiano",
}


class PlaceMetaSchema(pydantic.BaseModel):
    """Minimal place metadata for edge meta-tag injection."""

    slug: str = Field(description="Place slug")
    name: str = Field(description="Place name")
    description: str = Field(description="Short meta description")
    categories: list[str] = Field(default_factory=list, description="Category names")
    elevation: int | None = Field(None, description="Elevation in meters")
    latitude: float | None = Field(None, description="WGS84 latitude")
    longitude: float | None = Field(None, description="WGS84 longitude")
    image: str | None = Field(None, description="Social preview image (absolute URL)")
    page_url: str = Field(description="Canonical frontend page URL")
    jsonld: dict | None = Field(None, description="Ready-to-inline schema.org JSON-LD")
    modified: str | None = Field(None, description="Last modification (ISO date)")


class _PlaceSlugPath(pydantic.BaseModel):
    """Place slug path parameter."""

    slug: str = Field(description="Place slug")


class _MetaQuery(pydantic.BaseModel):
    """No extra query parameters (texts are stored per place)."""

    model_config = pydantic.ConfigDict(extra="ignore")


def _languages_line(slug: str) -> str:
    """Footer links to this document in every supported language."""
    base = f"{settings.FRONTEND_DOMAIN.rstrip('/')}/geo/places/{slug}.md"
    links = [
        f"[{label}]({base}?lang={code})" for code, label in _LANGUAGE_LABELS.items()
    ]
    return "·".join(links)


def _place_url(place: GeoPlace) -> str:
    pattern = settings.PLACE_URL_PATTERN  # e.g. "place/{slug}"
    return f"{settings.FRONTEND_DOMAIN.rstrip('/')}/{pattern.format(slug=place.slug)}"


def _place_image(place: GeoPlace, request: HttpRequest) -> str | None:
    """Highest-scored *servable* image as og:image; static-map card as
    fallback.

    Same visibility filters and source resolution as the hut meta
    endpoint (``_hut_meta._og_image``): pinned external images serve
    from ``source_url_raw``, rows with no source are skipped instead of
    signing an empty path."""
    associations = (
        GeoPlaceImageAssociation.objects.filter(
            geo_place=place,
            image__is_active=True,
            image__review_status=Image.ReviewStatusChoices.approved,
        )
        .exclude(image__license__no_publication=True)
        .select_related("image")
        .order_by("-score", "id")
    )
    for association in associations:
        source = photo_source(association.image)
        if source is None:
            continue
        focal = (association.image.image_meta or {}).get("focal")
        og_url = None
        try:  # preview image is best-effort
            og_url = og_photo_url(source, focal)
        except Exception:
            og_url = None
        if og_url:
            return og_url
    # Complete static-map card from the generic endpoint; v=<modified>
    # busts the render cache on ANY place change, ETag-style.
    from urllib.parse import urlencode

    query = urlencode(
        {
            "place": place.slug,
            "zoom": 16,
            "v": f"{place.modified:%Y%m%dT%H%M%S}",
        }
    )
    return og_map_card_url(request.build_absolute_uri(f"/v1/geo/map/static?{query}"))


def _place_description(place: GeoPlace) -> str:
    """Format: category name verbatim + elevation, nothing invented
    (place texts are stored per place, no lang parameter here).
    Falls back to a located-only sentence, then the bare name."""
    category = next((c.name for c in place.categories.all() if c.name), None)
    ele = int(place.elevation) if place.elevation else None
    if category and ele:
        return f"{_cap_first(category)} auf {ele} m über Meer."
    if category:
        return f"{_cap_first(category)}."
    if ele:
        return f"Gelegen auf {ele} m über Meer."
    return place.name


def _cap_first(label: str) -> str:
    return label[0].upper() + label[1:] if label else label


def _place_jsonld(
    place: GeoPlace, description: str, page_url: str, image: str | None
) -> dict:
    data: dict = {
        "@context": "https://schema.org",
        "@type": "Place",
        "name": place.name,
        "description": description,
        "url": page_url,
    }
    if image:
        data["image"] = image
    if place.location:
        data["geo"] = {
            "@type": "GeoCoordinates",
            "latitude": round(place.location.y, 6),
            "longitude": round(place.location.x, 6),
        }
    if place.elevation:
        data["additionalProperty"] = [
            {
                "@type": "PropertyValue",
                "name": "elevation",
                "value": f"{place.elevation} m",
            }
        ]
    return data


def _get_public_place(slug: str) -> GeoPlace:
    place = (
        GeoPlace.objects.filter(is_active=True, is_public=True, slug=slug)
        .prefetch_related("categories")
        .first()
    )
    if place is None:
        msg = f"Could not find place '{slug}'."
        raise Http404(msg)
    return place


class PlaceMetaController(ApiController):
    """Minimal place metadata for the edge."""

    @modify(
        operation_id="get_place_meta",
        headers=cache_headers(CACHE_TTL),
    )
    def get(
        self,
        parsed_path: Path[_PlaceSlugPath],
        parsed_query: Query[_MetaQuery],
    ) -> PlaceMetaSchema:
        """Get place metadata.

        Minimal place metadata for HTML meta-tag injection at the edge.
        """
        place = _get_public_place(parsed_path.slug)
        page_url = _place_url(place)
        image = _place_image(place, self.request)
        description = _place_description(place)

        return PlaceMetaSchema(
            slug=place.slug,
            name=place.name,
            description=description,
            categories=[c.name for c in place.categories.all() if c.name],
            elevation=place.elevation,
            latitude=round(place.location.y, 6) if place.location else None,
            longitude=round(place.location.x, 6) if place.location else None,
            image=image,
            page_url=page_url,
            jsonld=_place_jsonld(place, description, page_url, image),
            modified=place.modified.isoformat() if place.modified else None,
        )


def get_place_markdown(request: HttpRequest, slug: str) -> HttpResponse:
    """A place as a self-contained Markdown document for LLM agents."""
    place = _get_public_place(slug)
    page_url = _place_url(place)
    categories = ", ".join(c.name for c in place.categories.all() if c.name)

    overview: list[tuple[str, str]] = [
        ("Categories", categories or None),
        ("Elevation", f"{place.elevation} m" if place.elevation else None),
        (
            "Coordinates",
            f"{place.location.y:.6f}, {place.location.x:.6f}"
            if place.location
            else None,
        ),
    ]
    overview_rows = "\n".join(
        f"| {label} | {value} |" for label, value in overview if value
    )

    markdown = f"""# {place.name}

> {categories}

Map: {page_url}

## Overview

| | |
| --- | --- |
{overview_rows}

## Description

{place.description or "—"}

Languages: {_languages_line(place.slug)}

---

Data: [Wodore]({settings.FRONTEND_DOMAIN.rstrip("/")}) · JSON: {page_url} · Last updated: {place.modified:%Y-%m-%d}
"""  # noqa: WPS237
    response = HttpResponse(markdown, content_type="text/markdown; charset=utf-8")
    response["Cache-Control"] = f"public, max-age={CACHE_TTL}"
    return response


paths = [
    path(
        "places/<str:slug>/meta",
        PlaceMetaController.as_view(),
        name="get_place_meta",
    ),
    external_path(
        "places/<str:slug>.md",
        get_place_markdown,
        openapi=None,
        name="get_place_markdown",
    ),
]

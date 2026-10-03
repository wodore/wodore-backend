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
from server.apps.images.og import og_photo_url

from .models import GeoPlace

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
    """Preview image URL straight from the image service's gallery
    response (``place_gallery_response`` — the ``cached_only=true``
    fast call, default parameters):

    * a photo feature → imagor og size with the Wodore logo composited
      at the bottom, a bit left of center;
    * the service's static-map fallback feature (``is_fallback``) → its
      card URL as-is (already og-sized: zoom 15, spotlight effect,
      marker, watermark baked into the render).

    Everything else (pinned/curated rows) is the image service's
    business. Degenerate places without a location have no image."""
    from .api_images import place_gallery_response

    response = place_gallery_response(place, request)
    for feature in response.features:
        props = feature.properties
        if props is None:
            continue
        if props.is_fallback:
            landscape = props.urls.landscape
            url = (landscape.md if landscape is not None else None) or (
                props.urls.original.raw or None
            )
            if url:
                return url
            continue
        raw = props.urls.original.raw
        if not raw:
            continue
        og_url = None
        try:  # preview image is best-effort
            og_url = og_photo_url(raw, request=request)
        except Exception:
            og_url = None
        if og_url:
            return og_url
    return None


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

"""SEO/LLM surface for places: lean meta + Markdown documents.

Mirrors the hut surface (``server/apps/huts/api/_hut_meta.py`` and
``_hut_markdown.py``) for ``GeoPlace``:

* ``/v1/geo/places/{slug}/meta`` — minimal contract for edge meta-tag
  injection (frontend route TBD; see ``PLACE_URL_PATTERN``)
* ``/v1/geo/places/{slug}.md`` — self-contained Markdown document

GeoPlace texts are stored per place (``main_language``), not per-active
language like huts — the endpoints serve the stored text as-is.
"""

from ninja import Field, Schema

from django.conf import settings
from django.http import Http404, HttpRequest, HttpResponse

from server.apps.images.og import og_card_url, og_photo_url

from .api import router
from .models import GeoPlace, GeoPlaceImageAssociation

CACHE_TTL = 60 * 60


class PlaceMetaSchema(Schema):
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


def _place_url(place: GeoPlace) -> str:
    pattern = settings.PLACE_URL_PATTERN  # e.g. "place/{slug}"
    return f"{settings.FRONTEND_DOMAIN.rstrip('/')}/{pattern.format(slug=place.slug)}"


def _place_image(place: GeoPlace) -> str | None:
    """Highest-scored image as og:image; generated card as fallback."""
    association = (
        GeoPlaceImageAssociation.objects.filter(geo_place=place)
        .select_related("image")
        .order_by("-score", "id")
        .first()
    )
    try:
        if association is not None:
            source = str(association.image.image)
            if not source.startswith("http"):
                source = f"{settings.MEDIA_URL}/{source}"
            focal = (association.image.image_meta or {}).get("focal")
            return og_photo_url(source, focal)
    except Exception:
        pass
    subtitle = f"{place.elevation} m" if place.elevation else None
    return og_card_url(place.name, subtitle)


def _place_description(place: GeoPlace) -> str:
    parts = [place.name]
    if place.categories.exists():
        parts.append(", ".join(c.name for c in place.categories.all() if c.name))
    if place.elevation:
        parts.append(f"{place.elevation} m")
    return " – ".join([parts[0], " ".join(parts[1:])]) if len(parts) > 1 else parts[0]


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


@router.get(
    "/places/{slug}/meta", response=PlaceMetaSchema, operation_id="get_place_meta"
)
def get_place_meta(request: HttpRequest, response: HttpResponse, slug: str) -> dict:
    """Minimal place metadata for HTML meta-tag injection at the edge."""
    place = _get_public_place(slug)
    page_url = _place_url(place)
    image = _place_image(place)
    description = _place_description(place)

    response["Cache-Control"] = f"public, max-age={CACHE_TTL}"
    return {
        "slug": place.slug,
        "name": place.name,
        "description": description,
        "categories": [c.name for c in place.categories.all() if c.name],
        "elevation": place.elevation,
        "latitude": round(place.location.y, 6) if place.location else None,
        "longitude": round(place.location.x, 6) if place.location else None,
        "image": image,
        "page_url": page_url,
        "jsonld": _place_jsonld(place, description, page_url, image),
        "modified": place.modified.isoformat() if place.modified else None,
    }


@router.get(
    "/places/{slug}.md", include_in_schema=False, operation_id="get_place_markdown"
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

---

Data: [Wodore]({settings.FRONTEND_DOMAIN.rstrip("/")}) · JSON: {page_url} · Last updated: {place.modified:%Y-%m-%d}
"""
    response = HttpResponse(markdown, content_type="text/markdown; charset=utf-8")
    response["Cache-Control"] = f"public, max-age={CACHE_TTL}"
    return response

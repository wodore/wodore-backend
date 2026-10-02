"""Lean hut metadata for HTML meta-tag injection at the edge.

``/v1/huts/{slug}/meta`` returns the minimal, stable contract the
frontend nginx (njs) needs to inject ``<title>``, ``og:*``, canonical and
JSON-LD into the SPA shell for ``wodore.com/hut/{slug}`` requests — a
single-row query answering in ~15 fields instead of the full detail
endpoint's annotated payload. Responses are public and cacheable
(``Cache-Control: public, max-age=3600``); the edge caches them on its
own volume with its own TTL.

Localized via the same ``lang`` parameter as the JSON API (data fields
follow the active language, glue words get a small per-language table).
The ``jsonld`` block is pre-built so the edge script can inline it
verbatim.
"""

from ninja import Field, Schema

from django.conf import settings
from django.http import Http404, HttpRequest, HttpResponse

from server.apps.images.og import og_card_url, og_map_card_url, og_photo_url
from server.apps.symbols.utils import resolve_symbol_urls
from server.apps.translations import LanguageParam, activate, with_language_param

from ..models import Hut, HutImageAssociation
from ._router import router

CACHE_TTL = 60 * 60

# Glue words for the short meta description.
_PLACES = {"de": "Plätze", "en": "places", "fr": "places", "it": "posti"}
_AND = {"de": "mit", "en": "with", "fr": "avec", "it": "con"}


class HutMetaSchema(Schema):
    slug: str = Field(description="Hut slug")
    name: str = Field(description="Hut name (localized)")
    description: str = Field(description="Short meta description (localized)")
    lang: str = Field(description="Language the localized fields resolve to")
    type_standard: str | None = Field(
        None, description="Building/hut type in standard operation"
    )
    type_reduced: str | None = Field(
        None,
        description="Building/hut type during reduced operation (e.g. winter room)",
    )
    elevation: float | None = Field(None, description="Elevation in meters")
    latitude: float | None = Field(None, description="WGS84 latitude")
    longitude: float | None = Field(None, description="WGS84 longitude")
    capacity_standard: int | None = Field(
        None, description="Capacity in standard operation"
    )
    capacity_reduced: int | None = Field(
        None, description="Capacity during reduced operation"
    )
    owner: str | None = Field(None, description="Owner name")
    image: str | None = Field(None, description="Social preview image (absolute URL)")
    page_url: str = Field(description="Canonical frontend page URL")
    jsonld: dict | None = Field(None, description="Ready-to-inline schema.org JSON-LD")
    modified: str | None = Field(None, description="Last modification (ISO date)")


def _og_image(hut: Hut, request: HttpRequest) -> str:
    """Preview image URL: the highest-scored image at the og size;
    generated brand card (name + elevation) as fallback."""
    association = (
        HutImageAssociation.objects.filter(hut=hut)
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
    symbol_url = None
    if hut.hut_type_open is not None:
        symbols = resolve_symbol_urls(hut.hut_type_open, {"request": request})
        symbol_url = symbols.get("detailed") if symbols else None
    if hut.location is not None:
        # Complete static-map card (OpenTopoMap, type symbol marker,
        # watermark) from the generic endpoint; v=<modified> busts the
        # render/storage cache on ANY hut change, ETag-style.
        from urllib.parse import urlencode

        query = urlencode(
            {
                "place": hut.slug,
                "place_type": "hut",
                "zoom": 16,
                "v": f"{hut.modified:%Y%m%dT%H%M%S}",
            }
        )
        return og_map_card_url(
            request.build_absolute_uri(f"/v1/geo/map/static?{query}")
        )
    return og_card_url(symbol_url)


def _meta_description(hut: Hut, lang: str) -> str:
    places = _PLACES.get(lang, _PLACES["en"])
    with_word = _AND.get(lang, _AND["en"])
    parts = [hut.name]
    types = " / ".join(
        t.name for t in (hut.hut_type_open, hut.hut_type_closed) if t and t.name
    )
    capacity = hut.capacity_open or hut.capacity_closed
    details = []
    if types:
        detail = types
        if capacity:
            detail += f" {with_word} {capacity} {places}"
        details.append(detail)
    if hut.elevation:
        details.append(f"{int(hut.elevation)} m")
    if hut.hut_owner and hut.hut_owner.name:
        details.append(hut.hut_owner.name)
    return " – ".join(parts + [" ".join(details)]) if details else parts[0]


def _jsonld(hut: Hut, description: str, page_url: str, image: str | None) -> dict:
    data: dict = {
        "@context": "https://schema.org",
        "@type": "LodgingBusiness",
        "name": hut.name,
        "description": description,
        "url": page_url,
    }
    if image:
        data["image"] = image
    if hut.location:
        data["geo"] = {
            "@type": "GeoCoordinates",
            "latitude": round(hut.location.y, 6),
            "longitude": round(hut.location.x, 6),
        }
    if hut.elevation:
        data["additionalProperty"] = [
            {
                "@type": "PropertyValue",
                "name": "elevation",
                "value": f"{int(hut.elevation)} m",
            }
        ]
    return data


@router.get("/{slug}/meta", response=HutMetaSchema, operation_id="get_hut_meta")
@with_language_param()
def get_hut_meta(
    request: HttpRequest,
    response: HttpResponse,
    slug: str,
    lang: LanguageParam,
) -> dict:
    """Minimal hut metadata for HTML meta-tag injection at the edge."""
    activate(lang)
    hut = (
        Hut.objects.select_related("hut_owner", "hut_type_open", "hut_type_closed")
        .filter(is_active=True, is_public=True, slug=slug)
        .first()
    )
    if hut is None:
        msg = f"Could not find '{slug}'."
        raise Http404(msg)

    page_url = f"{settings.FRONTEND_DOMAIN.rstrip('/')}/hut/{hut.slug}"
    image = _og_image(hut, request)
    description = _meta_description(hut, lang)

    response["Cache-Control"] = f"public, max-age={CACHE_TTL}"
    return {
        "slug": hut.slug,
        "name": hut.name,
        "description": description,
        "lang": lang,
        "type_standard": hut.hut_type_open.name if hut.hut_type_open else None,
        "type_reduced": hut.hut_type_closed.name if hut.hut_type_closed else None,
        "elevation": float(hut.elevation) if hut.elevation else None,
        "latitude": round(hut.location.y, 6) if hut.location else None,
        "longitude": round(hut.location.x, 6) if hut.location else None,
        "capacity_standard": hut.capacity_open,
        "capacity_reduced": hut.capacity_closed,
        "owner": hut.hut_owner.name if hut.hut_owner else None,
        "image": image,
        "page_url": page_url,
        "jsonld": _jsonld(hut, description, page_url, image),
        "modified": hut.modified.isoformat() if hut.modified else None,
    }

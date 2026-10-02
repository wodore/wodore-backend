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

# Sentence glue per language: only facts that exist go in — capacity,
# elevation, reduced operation, closure. Never opening times or
# availability (not part of this endpoint's data).
_SENTENCES = {
    "de": {
        "full": "{label} mit {cap} Plätzen auf {ele} m über Meer.",
        "cap": "{label} mit {cap} Plätzen.",
        "ele": "{label} auf {ele} m über Meer.",
        "bare": "{label}.",
        "reduced": "Reduzierter Betrieb als {label} mit {cap} Plätzen.",
        "reduced_bare": "Reduzierter Betrieb als {label}.",
        "closed": "Derzeit geschlossen.",
        "located": "Gelegen auf {ele} m über Meer.",
    },
    "en": {
        "full": "{label} with {cap} places at {ele} m above sea level.",
        "cap": "{label} with {cap} places.",
        "ele": "{label} at {ele} m above sea level.",
        "bare": "{label}.",
        "reduced": "Reduced operation as {label} with {cap} places.",
        "reduced_bare": "Reduced operation as {label}.",
        "closed": "Currently closed.",
        "located": "Located at {ele} m above sea level.",
    },
    "fr": {
        "full": "{label} avec {cap} places à {ele} m d'altitude.",
        "cap": "{label} avec {cap} places.",
        "ele": "{label} à {ele} m d'altitude.",
        "bare": "{label}.",
        "reduced": "En exploitation réduite, {label} avec {cap} places.",
        "reduced_bare": "En exploitation réduite, {label}.",
        "closed": "Actuellement fermé.",
        "located": "Situé à {ele} m d'altitude.",
    },
    "it": {
        "full": "{label} con {cap} posti a {ele} m s.l.m.",
        "cap": "{label} con {cap} posti.",
        "ele": "{label} a {ele} m s.l.m.",
        "bare": "{label}.",
        "reduced": "In esercizio ridotto, {label} con {cap} posti.",
        "reduced_bare": "In esercizio ridotto, {label}.",
        "closed": "Attualmente chiuso.",
        "located": "Situato a {ele} m s.l.m.",
    },
}


def _cap_first(label: str) -> str:
    return label[0].upper() + label[1:] if label else label


def _type_sentence(
    slug: str | None, name: str | None, lang: str, cap: int | None, ele: float | None
) -> str | None:
    """First sentence: type + capacity + elevation. The type word is the
    category's ``name`` verbatim (translation-aware: whatever the active
    language resolves to, German today) — nothing is invented here.
    Returns ``None`` for closed/unknown types (handled separately)."""
    label = name if name and slug not in ("unknown", None) else None
    if not label:
        return None
    t = _SENTENCES[lang]
    ele_i = int(ele) if ele else None
    if cap:
        if ele_i:
            return t["full"].format(label=_cap_first(label), cap=cap, ele=ele_i)
        return t["cap"].format(label=_cap_first(label), cap=cap)
    if ele_i:
        return t["ele"].format(label=_cap_first(label), ele=ele_i)
    return t["bare"].format(label=_cap_first(label))


def _meta_title(hut: Hut) -> str:
    """ "{name} · {owner}"" — the owner (typically the SAC section) keeps
    the title short; middle dot as separator."""
    owner = hut.hut_owner.name if hut.hut_owner else None
    if owner and owner not in hut.name:
        return f"{hut.name} · {owner}"
    return hut.name


def _meta_description(hut: Hut, lang: str) -> str:
    """Short, factual sentences for crawlers and link previews — built
    only from fields that exist (type, capacities, elevation, reduced
    operation, closure). Never invents opening times or availability."""
    t = _SENTENCES[lang]
    open_slug = getattr(hut.hut_type_open, "slug", None)
    open_name = getattr(hut.hut_type_open, "name", None)
    closed_slug = getattr(hut.hut_type_closed, "slug", None)
    closed_name = getattr(hut.hut_type_closed, "name", None)
    cap = hut.capacity_open or None
    ele = float(hut.elevation) if hut.elevation else None

    sentences: list[str] = []
    if open_slug == "closed":
        sentences.append(t["closed"])
        if ele:
            sentences.append(t["located"].format(ele=int(ele)))
    else:
        first = _type_sentence(open_slug, open_name, lang, cap, ele)
        if first:
            sentences.append(first)
        elif ele:
            sentences.append(t["located"].format(ele=int(ele)))
        # Reduced operation: the reduced-mode category name verbatim.
        if closed_slug and closed_slug not in ("closed", "unknown") and closed_name:
            cap2 = hut.capacity_closed or None
            if cap2:
                sentences.append(t["reduced"].format(label=closed_name, cap=cap2))
            else:
                sentences.append(t["reduced_bare"].format(label=closed_name))
    if not sentences:
        return hut.name
    return " ".join(sentences)


class HutMetaSchema(Schema):
    slug: str = Field(description="Hut slug")
    name: str = Field(description="Hut name (localized)")
    title: str = Field(description="Meta title: name · owner")
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
    title = _meta_title(hut)

    response["Cache-Control"] = f"public, max-age={CACHE_TTL}"
    return {
        "slug": hut.slug,
        "name": hut.name,
        "title": title,
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

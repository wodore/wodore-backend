"""Technical image assessment: perceptual hash + quality score.

Zero dependencies beyond Pillow and numpy; pixels always come from our own
imagor (cached thumbnails) — never from the origin. Results are intrinsic
to the image (not per-place): ``Image.phash`` / ``Image.quality_score``
columns plus a per-signal breakdown in ``image_meta.quality``.

Near-duplicates are detected within a place by Hamming distance of the
hashes (≤ ``DUPLICATE_HAMMING_DISTANCE``); the weaker twin(s) get a
``duplicate_of`` marker in ``image_meta`` — never hidden or deleted
automatically. The ThumbHash placeholder is computed by imagor itself
(``/meta/filters:thumbhash()``) — the image pipeline already decodes
the pixels there.
"""

import io

import requests
import structlog
from PIL import Image as PILImage

logger = structlog.get_logger()

#: Hamming distance at which two 64-bit hashes count as near-duplicates.
DUPLICATE_HAMMING_DISTANCE = 8

#: Thumbnail size used for hashing and metrics — small, fast, sufficient.
ASSESS_SIZE = (9, 8)

#: Source preview fetched from our own imagor for assessment.
ASSESS_FETCH_WIDTH = 500


def dhash64(image: PILImage.Image) -> str:
    """64-bit difference hash as 16 hex chars.

    Resize to 9x8 grayscale, compare horizontal neighbours, pack the 64
    comparison bits big-endian. Survives rescaling and re-compression —
    near-duplicates sit within a small Hamming distance.
    """
    gray = image.convert("L").resize(ASSESS_SIZE, PILImage.Resampling.LANCZOS)
    pixels = list(gray.getdata())
    bits = 0
    for row in range(8):
        for col in range(8):
            left = pixels[row * 9 + col]
            right = pixels[row * 9 + col + 1]
            bits = (bits << 1) | (1 if left > right else 0)
    return f"{bits:016x}"


def hamming_distance(hash_a: str, hash_b: str) -> int:
    """Hamming distance between two hex hashes."""
    return (int(hash_a, 16) ^ int(hash_b, 16)).bit_count()


def quality_metrics(image: PILImage.Image) -> dict:
    """Technical quality signals from numpy statistics (no ML).

    sharpness: variance of the Laplacian (high = sharp, low = blurred);
    exposure: share of clipped shadows/highlights; contrast: luminance
    standard deviation; saturation: mean colorfulness (catches gray
    street tiles/scans).
    """
    import numpy as np

    gray = np.asarray(image.convert("L").resize((256, 256)), dtype=np.float32)

    # Laplacian via explicit kernel (numpy only).
    kernel = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], dtype=np.float32)
    padded = np.pad(gray, 1)
    laplacian = sum(
        kernel[r, c] * padded[r : r + 256, c : c + 256]
        for r in range(3)
        for c in range(3)
    )
    sharpness = float(laplacian.var())

    total = gray.size
    dark_share = float((gray < 8).sum()) / total
    bright_share = float((gray > 247).sum()) / total
    contrast = float(gray.std())
    saturation = float(
        np.asarray(image.convert("HSV").resize((128, 128)))[..., 1].mean()
    )

    return {
        "sharpness": round(sharpness, 2),
        "dark_share": round(dark_share, 4),
        "bright_share": round(bright_share, 4),
        "contrast": round(contrast, 2),
        "saturation": round(saturation, 2),
    }


def technical_score(metrics: dict, width: int | None, height: int | None) -> int:
    """Combine the signals into a 0–100 score (heuristic, monotonic).

    Deliberately transparent: every factor is visible in the breakdown so
    the score can be argued with (and tuned) — no model involved.
    """
    # Sharpness: typical sharp photos land >100 variance, blurred <30.
    sharp_factor = min(metrics["sharpness"] / 150.0, 1.0)
    # Exposure: clipped pixels directly subtract.
    exposure_penalty = min(metrics["dark_share"] + metrics["bright_share"], 0.5)
    # Contrast: <20 std is flat haze, >50 is fine.
    contrast_factor = min(max(metrics["contrast"] / 50.0, 0.0), 1.0)
    # Resolution: below 800px on the long edge is weak material.
    long_edge = max(width or 0, height or 0)
    resolution_factor = min(long_edge / 1600.0, 1.0) if long_edge else 0.5

    score = 100 * (
        0.45 * sharp_factor
        + 0.25 * contrast_factor
        + 0.20 * resolution_factor
        + 0.10 * min(metrics["saturation"] / 60.0, 1.0)
    )
    score -= 60 * exposure_penalty
    return max(0, min(100, round(score)))


def _thumb_url(image) -> str | None:
    """500px preview URL served by our own imagor (never the origin)."""
    from server.apps.images.transfomer import ImagorImage

    source = image.image if getattr(image, "image", None) else image.source_url_raw
    if not source:
        return None
    return (
        ImagorImage(source)
        .transform(size=f"{ASSESS_FETCH_WIDTH}x{ASSESS_FETCH_WIDTH}", fit=True)
        .get_full_url()
    )


def _meta_url(image) -> str | None:
    """Signed imagor metadata URL computing the ThumbHash placeholder.

    ``GET {imagor}/{sig}/meta/filters:thumbhash()/<source>`` returns JSON
    with ``thumbhash`` — the pixel decoding happens in imagor, which has
    the source cached anyway.
    """
    from django.conf import settings

    from server.apps.images.transfomer import ImagorImage

    source = image.image if getattr(image, "image", None) else image.source_url_raw
    if not source:
        return None
    path = (
        f"meta/filters:thumbhash()/"
        f"{ImagorImage.url_quote(str(source).strip('/'), quote='yes')}"
    )
    signature = ImagorImage.sign_path(path) or "unsafe"
    return f"{settings.IMAGOR_URL}/{signature}/{path}"


def _fetch_thumbhash(image) -> str | None:
    """ThumbHash from imagor's metadata endpoint (None on any failure)."""
    url = _meta_url(image)
    if not url:
        return None
    try:
        response = requests.get(url, timeout=20)
        response.raise_for_status()
        return response.json().get("thumbhash")
    except Exception as e:
        logger.debug("thumbhash_fetch_failed", image_id=str(image.id), error=str(e))
        return None


def assess_image(image, *, force: bool = False) -> bool:
    """Compute phash + quality + thumbhash for one image; True when written.

    Skips images that already carry both values unless ``force``.
    """
    if not force and image.phash and image.quality_score is not None:
        return False

    url = _thumb_url(image)
    if not url:
        return False
    try:
        response = requests.get(url, timeout=20)
        response.raise_for_status()
        pil = PILImage.open(io.BytesIO(response.content))
        pil.load()
    except Exception as e:
        logger.warning("assess_fetch_failed", image_id=str(image.id), error=str(e))
        return False

    metrics = quality_metrics(pil)
    meta = dict(image.image_meta or {})
    from django.utils import timezone

    meta["quality"] = metrics
    meta["assessed_at"] = timezone.now().isoformat()
    image.phash = dhash64(pil)
    image.thumbhash = _fetch_thumbhash(image)
    variant_hashes = fetch_variant_thumbhashes(image)
    if variant_hashes:
        meta["thumbhashes"] = variant_hashes
    image.quality_score = technical_score(
        metrics, meta.get("width"), meta.get("height")
    )
    image.image_meta = meta
    image.save()
    return True


def assess_place_pins(place, *, force: bool = False) -> dict:
    """Assess a place's pins and mark near-duplicates within the place.

    The strongest image of a duplicate cluster (higher quality score,
    then larger original) stays primary; the others get
    ``image_meta.duplicate_of`` pointing at its source_ident.
    """
    from django.utils import timezone

    from server.apps.geometries.pinning import _association_for, place_type_of

    assoc_model, place_field, _inv = _association_for(place)
    assocs = assoc_model.objects.filter(
        **{place_field: place}, image__is_active=True
    ).select_related("image")

    assessed = duplicates = 0
    for assoc in assocs:
        if assess_image(assoc.image, force=force):
            assessed += 1

    # Duplicate clusters among the freshly/already hashed pins.
    hashed = [a.image for a in assocs if a.image.phash and a.image.is_active]
    by_quality = sorted(
        hashed,
        key=lambda img: (
            -(img.quality_score or 0),
            -(img.image_meta or {}).get("width") or 0,
        ),
    )
    primaries = []
    for image in by_quality:
        primary = None
        for candidate in primaries:
            if (
                hamming_distance(image.phash, candidate.phash)
                <= DUPLICATE_HAMMING_DISTANCE
            ):
                primary = candidate
                break
        meta = dict(image.image_meta or {})
        if primary is not None:
            if meta.get("duplicate_of") != primary.source_ident:
                meta["duplicate_of"] = primary.source_ident
                meta["assessed_at"] = timezone.now().isoformat()
                image.image_meta = meta
                image.save(update_fields=["image_meta"])
            duplicates += 1
        else:
            primaries.append(image)
            if "duplicate_of" in meta:
                del meta["duplicate_of"]
                image.image_meta = meta
                image.save(update_fields=["image_meta"])

    stats = {"assessed": assessed, "duplicates": duplicates, "pins": len(hashed)}
    logger.info(
        "place_pins_assessed",
        place=place.slug,
        place_type=place_type_of(place),
        **stats,
    )
    return stats


def assess_place_task(place_type: str, slug: str):
    """django-q2 entrypoint: assess a place's pins in the background."""
    try:
        from server.apps.geometries.pinning import _place_by_slug

        place = _place_by_slug(place_type, slug)
        if place is None:
            logger.warning("assess_place_not_found", place_type=place_type, place=slug)
            return
        assess_place_pins(place)
    except Exception:
        logger.exception("assess_place_failed", place_type=place_type, place=slug)


# ---------------------------------------------------------------------------
# Variant thumbhashes — one per rendering context (computed by imagor on the
# exact transformed URL, so each placeholder matches what its box shows).
# ---------------------------------------------------------------------------

#: image_meta.thumbhashes keys → (width, height) of the transformed variant.
THUMBHASH_VARIANT_SIZES = {
    "thumb_square": (200, 200),
    "thumb_landscape": (200, 133),
    "thumb_portrait": (133, 200),
    "preview_landscape": (400, 267),
    "preview_portrait": (300, 450),
}


def _focal_crop_params(image):
    """Focal/crop areas from image_meta, mirroring the serving pipeline.

    Serving semantics: thumbs crop to the focal area when defined (else the
    curated crop, else nothing); preview/medium/large only apply the curated
    crop, with focal (or smart) guiding imagor's aspect crop.
    """
    meta = image.image_meta or {}
    focal = meta.get("focal") or None
    crop = meta.get("crop") or None
    width = meta.get("width")
    height = meta.get("height")
    is_portrait = bool(width and height and height > width)

    focal_point = None
    focal_start = focal_stop = None
    if focal:
        focal_point = (
            f"{focal.get('x1', 0):.2f}x{focal.get('y1', 0):.2f}:"
            f"{focal.get('x2', 1):.2f}x{focal.get('y2', 1):.2f}"
        )  # same format as ImageArea.to_imagor_area()
        focal_start, focal_stop = focal_point.split(":")
    crop_start = crop_stop = None
    if crop:
        crop_start = f"{crop.get('x1', 0):g}x{crop.get('y1', 0):g}"
        crop_stop = f"{crop.get('x2', 1):g}x{crop.get('y2', 1):g}"
    return {
        "focal_point": focal_point,
        "focal_start": focal_start,
        "focal_stop": focal_stop,
        "crop_start": crop_start,
        "crop_stop": crop_stop,
        "is_portrait": is_portrait,
        "width": width,
        "height": height,
    }


def _variant_meta_urls(image) -> dict[str, str]:
    """Signed imagor metadata URLs computing the thumbhash per variant."""

    from django.conf import settings

    from server.apps.geometries.providers.base import _calculate_constrained_size
    from server.apps.images.transfomer import ImagorImage

    source = image.image if getattr(image, "image", None) else image.source_url_raw
    if not source:
        return {}
    params = _focal_crop_params(image)
    img = ImagorImage(source)  # FieldFile or URL string — the init maps media paths

    def meta_url(target_w, target_h, *, thumb: bool):
        size = "x".join(
            str(v)
            for v in _calculate_constrained_size(
                target_w, target_h, params["width"], params["height"]
            )
        )
        cs, ce = params["crop_start"], params["crop_stop"]
        if thumb:  # focal wins over the curated crop for thumbs
            cs = params["focal_start"] or params["crop_start"]
            ce = params["focal_stop"] or params["crop_stop"]
        # The /meta/ prefix must be part of the SIGNED path — build the
        # operations path first, then sign the whole thing.
        ops = img._build_path(
            size=size,
            crop_start=cs,
            crop_stop=ce,
            fit=False,
            stretch=False,
            halign=None,
            valign=None,
            focal=params["focal_point"] or "smart",
            quality=None,
            blur=None,
            filters=["thumbhash()"],
        )
        full = f"meta/{ops}"
        signature = ImagorImage.sign_path(full) or "unsafe"
        return f"{settings.IMAGOR_URL}/{signature}/{full}"

    urls = {
        "thumb_square": meta_url(200, 200, thumb=True),
        "thumb_landscape": meta_url(200, 133, thumb=True),
        "thumb_portrait": meta_url(133, 200, thumb=True),
    }
    if params["is_portrait"]:
        urls["preview"] = meta_url(300, 450, thumb=False)
    else:
        urls["preview"] = meta_url(400, 267, thumb=False)
    return urls


def fetch_variant_thumbhashes(image) -> dict[str, str]:
    """One thumbhash per rendering context, from imagor metadata calls."""
    hashes: dict[str, str] = {}
    for variant, url in _variant_meta_urls(image).items():
        try:
            response = requests.get(url, timeout=20)
            response.raise_for_status()
            value = response.json().get("thumbhash")
        except Exception as e:
            logger.debug(
                "variant_thumbhash_failed",
                image_id=str(image.id),
                variant=variant,
                error=str(e),
            )
            continue
        if value:
            hashes[variant] = value
    return hashes


def thumbhash_to_image(thumbhash: str):
    """Decode a ThumbHash to a PIL RGBA placeholder (reference port)."""
    import base64
    from math import cos, pi

    hash_ = base64.b64decode(thumbhash)
    header24 = hash_[0] | (hash_[1] << 8) | (hash_[2] << 16)
    header16 = hash_[3] | (hash_[4] << 8)
    l_dc = (header24 & 63) / 63
    p_dc = ((header24 >> 6) & 63) / 31.5 - 1
    q_dc = ((header24 >> 12) & 63) / 31.5 - 1
    l_scale = ((header24 >> 18) & 31) / 31
    has_alpha = header24 >> 23
    p_scale = ((header16 >> 3) & 63) / 63
    q_scale = ((header16 >> 9) & 63) / 63
    is_landscape = header16 >> 15
    lx = max(3, (5 if has_alpha else 7) if is_landscape else (header16 & 7))
    ly = max(3, (header16 & 7) if is_landscape else (5 if has_alpha else 7))
    a_dc = (hash_[5] & 15) / 15 if has_alpha else 1
    a_scale = (hash_[5] >> 4) / 15

    ac_start = 6 if has_alpha else 5
    state = {"i": 0}

    def decode_channel(nx, ny, scale):
        ac = []
        for cy in range(ny):
            start_cx = 0 if cy else 1
            for cx in range(start_cx, nx):
                if not (cx * ny < nx * (ny - cy)):
                    break
                byte = hash_[ac_start + (state["i"] >> 1)]
                shift = (state["i"] & 1) << 2
                state["i"] += 1
                ac.append((((byte >> shift) & 15) / 7.5 - 1) * scale)
        return ac

    l_ac = decode_channel(lx, ly, l_scale)
    p_ac = decode_channel(3, 3, p_scale * 1.25)
    q_ac = decode_channel(3, 3, q_scale * 1.25)
    a_ac = decode_channel(5, 5, a_scale) if has_alpha else None

    ratio = thumbhash_aspect_ratio(thumbhash)
    w = round(32 if ratio > 1 else 32 * ratio)
    h = round(32 / ratio if ratio > 1 else 32)

    pixels = []
    for y in range(h):
        fy = [
            cos(pi / h * (y + 0.5) * cy) for cy in range(max(ly, 5 if has_alpha else 3))
        ]
        for x in range(w):
            fx = [
                cos(pi / w * (x + 0.5) * cx)
                for cx in range(max(lx, 5 if has_alpha else 3))
            ]
            l, p, q, a = l_dc, p_dc, q_dc, a_dc
            j = 0
            for cy in range(ly):
                start_cx = 0 if cy else 1
                fy2 = fy[cy] * 2
                for cx in range(start_cx, lx):
                    if not (cx * ly < lx * (ly - cy)):
                        break
                    l += l_ac[j] * fx[cx] * fy2
                    j += 1
            j = 0
            for cy in range(3):
                start_cx = 0 if cy else 1
                fy2 = fy[cy] * 2
                for cx in range(start_cx, 3 - cy):
                    f = fx[cx] * fy2
                    p += p_ac[j] * f
                    q += q_ac[j] * f
                    j += 1
            if has_alpha:
                j = 0
                for cy in range(5):
                    start_cx = 0 if cy else 1
                    fy2 = fy[cy] * 2
                    for cx in range(start_cx, 5 - cy):
                        a += a_ac[j] * fx[cx] * fy2
                        j += 1
            b = l - 2 / 3 * p
            r = (3 * l - b + q) / 2
            g = r - q
            pixels.append(
                (
                    max(0, min(255, round(255 * max(0, min(1, r))))),
                    max(0, min(255, round(255 * max(0, min(1, g))))),
                    max(0, min(255, round(255 * max(0, min(1, b))))),
                    max(0, min(255, round(255 * max(0, min(1, a))))),
                )
            )
    return _put_pixels(w, h, pixels)


def _put_pixels(w, h, pixels):
    image = PILImage.new("RGBA", (w, h))
    image.putdata(pixels)
    return image


def thumbhash_aspect_ratio(thumbhash: str) -> float:
    """Approximate aspect ratio (w/h) encoded in a ThumbHash."""
    import base64

    hash_ = base64.b64decode(thumbhash)
    has_alpha = bool(hash_[2] & 0x80)
    is_landscape = bool(hash_[4] & 0x80)
    lx = (5 if has_alpha else 7) if is_landscape else (hash_[3] & 7)
    ly = (hash_[3] & 7) if is_landscape else (5 if has_alpha else 7)
    return lx / ly

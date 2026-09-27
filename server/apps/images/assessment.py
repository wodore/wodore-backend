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

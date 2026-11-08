"""Read/write orchestration: quota, validation, relay, cache, aggregates.

Everything the controllers do beyond HTTP shape lives here (design D5/D6).
Reads: subject-keyed local cache → blacklist + geo-match filters → local
pagination/aggregation, merged with the read-only refuges.info provider.
Writes: kill-switch → caller → quota → sign → log (pending) → relay →
log (accepted/failed) → write-through cache merge (the author's own
review is visible on the next read, regardless of TTL or upstream
indexing lag).

Subject names (design D1): ``q`` is the hut's **review name** — pinned
on the first review write; before that it resolves dynamically from the
OSM name (current ``HutSource`` org ``osm``) falling back to the hut
name. Two huts with the same normalized name within 2·u share reviews —
the accepted interop trade-off (MapComplete-compatible ``q``).
"""

import base64
import datetime
import json
import statistics
import typing as t
from http import HTTPStatus
from urllib.parse import urlencode, urlsplit

import structlog
from dmr import APIError

from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError
from django.http import HttpRequest
from django.utils import timezone

from server.apps.api.controller import raise_not_found
from server.apps.api.error_codes import ErrorCode
from server.apps.huts.models import Hut

from . import signing
from .client import (
    MangroveClient,
    ReviewItem,
    ReviewPayload,
    UpstreamRejected,
    UpstreamUnavailable,
    parse_geo_subject,
    subject_geo_matches,
)
from .models import (
    HutReviewSubject,
    ReviewBlacklist,
    ReviewerKey,
    ReviewerProfile,
    ReviewMergeRequest,
    SubmittedReview,
)
from .schemas import (
    ATTRIBUTION,
    LICENSE,
    BatchSummaryEnvelope,
    MyReviewOut,
    ReportOut,
    ReviewEditIn,
    ReviewImageOut,
    ReviewOut,
    ReviewReplyIn,
    ReviewReportIn,
    ReviewsEnvelope,
    ReviewSubmitIn,
    ReviewSummaryOut,
)

logger = structlog.get_logger(__name__)

_QUOTA_WINDOW = datetime.timedelta(hours=24)

#: How long cached upstream list payloads live (seconds).
_LIST_TTL = settings.MANGROVE_CACHE_TTL_LIST

_client: MangroveClient | None = None


def client() -> MangroveClient:
    """The process-wide upstream client (lazy; tests monkeypatch this)."""
    global _client
    if _client is None:
        _client = MangroveClient()
    return _client


# ── subject names (design D1: review name, pinned on first write) ────


def resolve_review_name(hut: Hut) -> str:
    """The hut's review name (``q``): pinned → OSM name → hut name."""
    pinned = HutReviewSubject.objects.filter(hut=hut).only("name").first()
    if pinned is not None:
        return pinned.name
    from server.apps.huts.models import HutSource

    osm = (
        HutSource.objects.filter(hut=hut, organization__slug="osm", is_current=True)
        .order_by("-created")
        .only("name")
        .first()
    )
    if osm is not None and osm.name.strip():
        return osm.name.strip()
    return hut.name


def pin_review_name(hut: Hut) -> str:
    """Pin the resolved name on the first review write (idempotent)."""
    name = resolve_review_name(hut)
    HutReviewSubject.objects.get_or_create(hut=hut, defaults={"name": name})
    return name


def build_geo_subject(lat: float, lon: float, q: str) -> str:
    """``geo:{lat:.6f},{lon:.6f}?q={q}&u={u}`` for an arbitrary ``q``."""
    return "geo:{:.6f},{:.6f}?{}&u={}".format(
        lat, lon, urlencode({"q": q}), settings.MANGROVE_U_RADIUS
    )


def subject_for_hut(hut: Hut) -> str:
    """The hut's Mangrove subject with the resolved review name as ``q``."""
    return build_geo_subject(hut.location.y, hut.location.x, resolve_review_name(hut))


def subject_for_q(q: str) -> str:
    """A subject built from a bare name (my-reviews annotation lookups)."""
    return build_geo_subject(0.0, 0.0, q)


# ── hut / caller resolution ──────────────────────────────────────────


def resolve_hut(slug: str) -> Hut:
    """The public active hut or 404 (no subject leakage)."""
    hut = (
        Hut.objects.filter(is_active=True, is_public=True, slug=slug)
        .only("slug", "location", "name")
        .first()
    )
    if hut is None:
        msg = f"Could not find hut '{slug}'."
        raise_not_found(msg)
    return t.cast(Hut, hut)


def caller_from_request(request: HttpRequest) -> t.Any | None:
    """The authenticated user: session user or bearer-token ``sub``.

    ``request.user`` is only populated for session auth (the ``/v1/my/``
    path). Bearer requests need the token payload: when dmr's auth did
    not run (this controller family enforces auth in ``dispatch``, not
    via ``auth=[AuthBearer()]``), validate the bearer token here with
    the same validator chain ``AuthBearer`` uses, then resolve ``sub``
    (user pk for the built-in provider) to a user.
    """
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        return user
    auth = getattr(request, "auth", None)
    if not isinstance(auth, dict):
        auth = _validate_bearer(request)
    if isinstance(auth, dict):
        sub = auth.get("sub")
        if sub is not None:
            from django.contrib.auth import get_user_model

            user_model = get_user_model()
            try:
                return user_model.objects.get(pk=sub)
            except (user_model.DoesNotExist, ValueError):
                logger.info("reviews_caller_unknown_sub")
                return None
    return None


def _validate_bearer(request: HttpRequest) -> dict[str, t.Any] | None:
    """Run the shared bearer validators on the request's token, if any."""
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if not token or scheme.lower() != "bearer":
        return None
    from server.apps.api.auth import _select_validators

    for validator in _select_validators():
        result = validator(
            token_string=token.strip(),
            scopes=None,
            roles=None,
            groups=None,
            request=request,
        )
        if result is not None:
            return result
    return None


def get_or_mint_key(user: t.Any) -> tuple[ReviewerKey, ReviewerProfile]:
    """The user's reviewer key + profile (lazily minted on first write)."""
    key = ReviewerKey.objects.filter(user=user).first()
    profile = ReviewerProfile.objects.filter(user=user).first()
    if key is None:
        kid, private_jwk = signing.mint_keypair()
        try:
            key = ReviewerKey.objects.create(
                user=user,
                kid=kid,
                private_jwk_encrypted=_encrypt(json.dumps(private_jwk)),
            )
        except IntegrityError:
            key = t.cast(ReviewerKey, ReviewerKey.objects.get(user=user))
    if profile is None:
        try:
            profile = ReviewerProfile.objects.create(user=user)
        except IntegrityError:
            profile = t.cast(ReviewerProfile, ReviewerProfile.objects.get(user=user))
    return key, profile


def _encrypt(jwk_json: str) -> str:
    from .models import encrypt_private_jwk

    return encrypt_private_jwk(jwk_json)


def _decrypt_key_jwk(key: ReviewerKey) -> dict[str, t.Any]:
    from cryptography.fernet import InvalidToken

    from .models import decrypt_private_jwk

    try:
        raw = decrypt_private_jwk(key.private_jwk_encrypted)
        return t.cast(dict[str, t.Any], json.loads(raw))
    except (InvalidToken, ValueError, TypeError) as exc:
        msg = (
            "ReviewerKey cannot be decrypted - the encryption secret "
            "was lost or rotated away (see AGENTS.md § Reviews)."
        )
        raise RuntimeError(msg) from exc


# ── quota (design D5/O7) ─────────────────────────────────────────────


def _quota_used(user: t.Any, actions: list[str]) -> int:
    since = timezone.now() - _QUOTA_WINDOW
    return SubmittedReview.objects.filter(
        user=user,
        action__in=actions,
        state__in=[SubmittedReview.State.accepted, SubmittedReview.State.failed],
        created__gte=since,
    ).count()


def enforce_quota(user: t.Any, kind: str) -> None:
    """429 with ``review_quota_exceeded`` when the window is exhausted."""
    if kind == "submit":
        limit = settings.MANGROVE_QUOTA_SUBMIT
        actions = [SubmittedReview.Action.review.value]
    else:
        limit = settings.MANGROVE_QUOTA_EDIT
        actions = [
            SubmittedReview.Action.edit.value,
            SubmittedReview.Action.delete.value,
        ]
    used = _quota_used(user, actions)
    if used < limit:
        return
    reset_at = (
        SubmittedReview.objects.filter(
            user=user, action__in=actions, created__gte=timezone.now() - _QUOTA_WINDOW
        )
        .order_by("created")
        .values_list("created", flat=True)
        .first()
    )
    reset = (reset_at + _QUOTA_WINDOW) if reset_at else (timezone.now() + _QUOTA_WINDOW)
    retry_after = max(1, int((reset - timezone.now()).total_seconds()))
    raise APIError(
        {
            "code": ErrorCode.review_quota_exceeded,
            "detail": f"Review quota exceeded ({used}/{limit} in the last 24 h). "
            f"Resets at {reset.isoformat()}.",
        },
        status_code=HTTPStatus.TOO_MANY_REQUESTS,
        headers={"Retry-After": str(retry_after)},
    )


def enforce_enabled() -> None:
    """Kill-switch: writes refuse cleanly when disabled (design D10)."""
    if not settings.MANGROVE_ENABLED:
        raise APIError(
            {
                "code": ErrorCode.service_unavailable,
                "detail": "Review writing is temporarily disabled.",
            },
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
        )


# ── OSM metadata (design D8) ─────────────────────────────────────────


def osm_id_for_hut(hut: Hut) -> str | None:
    """``{osm_type}/{source_id}`` from the current OSM HutSource, or None.

    NEVER appends ``HutSource.version`` — that is Wodore's internal
    revision counter, not an OSM element version.
    """
    from server.apps.huts.models import HutSource

    source = (
        HutSource.objects.filter(hut=hut, organization__slug="osm", is_current=True)
        .order_by("-created")
        .only("source_id", "source_data")
        .first()
    )
    if source is None:
        return None
    data = source.source_data or {}
    osm_type = str(data.get("osm_type", "")).lower()
    if (
        osm_type not in ("node", "way", "relation")
        or not str(source.source_id).isdigit()
    ):
        return None
    osm_id = f"{osm_type}/{source.source_id}"
    return osm_id if len(osm_id) <= 50 else None


# ── cache (design D6: 15 min TTL + write-through merge) ──────────────


def _list_cache_key(subject: str) -> str:
    return f"reviews:list:{subject}"


def _replies_cache_key(signature: str) -> str:
    return f"reviews:replies:{signature}"


def _invalidate_subject(subject: str) -> None:
    cache.delete(_list_cache_key(subject))


def _cached_items(subject: str) -> list[ReviewItem] | None:
    """Cached upstream list for a subject; ``None`` on miss (checked!).

    Upstream infra failures map to the sanitized 503 (design D6).
    """
    if not settings.MANGROVE_ENABLED:
        return []
    cached = cache.get(_list_cache_key(subject))
    if cached is not None:
        return [ReviewItem.model_validate(item) for item in cached]
    try:
        response = client().list_reviews(subject)
    except UpstreamUnavailable as exc:
        raise _upstream_unavailable() from exc
    items = [item for item in response.reviews if item.payload.action is None]
    cache.set(
        _list_cache_key(subject), [item.model_dump() for item in items], _LIST_TTL
    )
    return items


def _store_items(subject: str, items: list[ReviewItem]) -> None:
    cache.set(
        _list_cache_key(subject), [item.model_dump() for item in items], _LIST_TTL
    )


def _item_from_own_jwt(jwt: str, target_signature: str) -> ReviewItem | None:
    """Rebuild a ReviewItem from a JWT Wodore just signed (cache merge).

    Best-effort: the JWT is our own construction — an unparseable one
    skips the cache merge (logged) instead of failing a relay that
    already succeeded upstream.
    """
    try:
        payload = t.cast(
            dict[str, t.Any],
            json.loads(
                base64.urlsafe_b64decode(
                    jwt.split(".")[1] + "=" * ((4 - len(jwt.split(".")[1]) % 4) % 4)
                )
            ),
        )
    except (ValueError, TypeError) as exc:
        logger.warning("reviews_own_jwt_unparsable", error=type(exc).__name__)
        return None
    return ReviewItem(
        jwt=jwt,
        kid=_header_kid(jwt),
        payload=ReviewPayload(
            iat=int(payload.get("iat", 0)),
            sub=str(payload.get("sub", "")),
            rating=payload.get("rating"),
            opinion=payload.get("opinion"),
            images=None,
            metadata=payload.get("metadata"),
        ),
        signature=signing.jwt_signature(jwt),
        original_sub=target_signature or None,
    )


def _header_kid(jwt: str) -> str:
    try:
        header = t.cast(
            dict[str, t.Any],
            json.loads(
                base64.urlsafe_b64decode(
                    jwt.split(".")[0] + "=" * ((4 - len(jwt.split(".")[0]) % 4) % 4)
                )
            ),
        )
    except (ValueError, TypeError):
        return ""
    return str(header.get("kid", ""))


def _merge_into_cache(subject: str, item: ReviewItem | None) -> None:
    """Write-through merge: the author's own review is immediately visible.

    Prepends the item to the cached list when a cache entry exists (no
    entry → the next read fetches fresh; unparseable item → skip).
    Immune to upstream indexing lag, which a plain invalidation is not.
    """
    if item is None:
        return
    cached = cache.get(_list_cache_key(subject))
    if cached is None:
        return
    items = [item] + [
        i
        for i in (ReviewItem.model_validate(i) for i in cached)
        if i.signature != item.signature
    ]
    _store_items(subject, items)


def _update_cached_item(
    subject: str, signature: str, rating: int | None, opinion: str | None
) -> None:
    """Write-through edit: update the cached copy of the edited review."""
    cached = cache.get(_list_cache_key(subject))
    if cached is None:
        return
    items: list[ReviewItem] = []
    for raw in cached:
        item = ReviewItem.model_validate(raw)
        if item.signature == signature:
            item = item.model_copy(
                update={
                    "payload": item.payload.model_copy(
                        update={"rating": rating, "opinion": opinion}
                    )
                }
            )
        items.append(item)
    _store_items(subject, items)


def _remove_cached_item(subject: str, signature: str) -> None:
    """Write-through delete: drop the deleted review from the cache."""
    cached = cache.get(_list_cache_key(subject))
    if cached is None:
        return
    items = [
        item
        for item in (ReviewItem.model_validate(i) for i in cached)
        if item.signature != signature
    ]
    _store_items(subject, items)


def _visible_items(
    subject: str, blacklisted: "set[str] | None" = None
) -> list[ReviewItem]:
    """Cached list, blacklist- and geo-filtered, newest first."""
    items = _cached_items(subject) or []
    if blacklisted is None:
        blacklisted = set(ReviewBlacklist.objects.values_list("signature", flat=True))
    visible = [
        item
        for item in items
        if item.signature not in blacklisted
        and subject_geo_matches(item.payload.sub, subject)
    ]
    visible.sort(key=lambda item: item.payload.iat, reverse=True)
    return visible


def _filtered_images(item: ReviewItem) -> list[ReviewImageOut]:
    """Images whose src is https AND on an allowlisted host (design D9)."""
    allow = set(settings.MANGROVE_IMAGE_HOST_ALLOWLIST)
    out: list[ReviewImageOut] = []
    for image in item.payload.images or []:
        parsed = urlsplit(image.src)
        if parsed.scheme == "https" and (parsed.hostname or "") in allow:
            out.append(ReviewImageOut(src=image.src, label=image.label))
    return out


def serialize_review(item: ReviewItem) -> ReviewOut:
    """Upstream item → response DTO (Mangrove source)."""
    metadata = item.payload.metadata or {}
    return ReviewOut(
        signature=item.signature,
        rating=item.payload.rating,
        opinion=item.payload.opinion,
        nickname=_str_or_none(metadata.get("nickname")),
        language=_str_or_none(metadata.get("language")),
        experience_context=_str_or_none(metadata.get("experience_context")),
        is_personal_experience=metadata.get("is_personal_experience") is True,
        is_affiliated=metadata.get("is_affiliated") is True,
        images=_filtered_images(item),
        created=datetime.datetime.fromtimestamp(
            item.payload.iat, tz=datetime.UTC
        ).isoformat(),
        source="mangrove",
        license=LICENSE,
        link=None,
    )


def _str_or_none(value: t.Any) -> str | None:
    return value if isinstance(value, str) and value else None


# ── read services ────────────────────────────────────────────────────


def _refuge_reviews(hut: Hut, blacklisted: "set[str] | None" = None) -> list[ReviewOut]:
    """Read-only refuges.info comments as reviews (source-attributed).

    The same signature blacklist applies (provider ids hide too).
    """
    from . import refuges_info

    point_id = refuges_info.point_id_for_hut(hut)
    if point_id is None:
        return []
    if blacklisted is None:
        blacklisted = set(ReviewBlacklist.objects.values_list("signature", flat=True))
    try:
        comments = refuges_info.comments_for_hut(hut)
    except Exception:
        logger.warning("refuges_info_failed", hut=hut.slug)
        return []
    link = refuges_info.point_url(point_id)
    return [
        ReviewOut(
            signature=comment.signature,
            rating=None,
            opinion=comment.text,
            nickname=comment.author,
            language=None,
            experience_context=None,
            is_personal_experience=False,
            is_affiliated=False,
            images=[],
            created=comment.created.isoformat(),
            source=refuges_info.SOURCE,
            license=refuges_info.LICENSE,
            link=link,
        )
        for comment in comments
        if comment.signature not in blacklisted
    ]


def visible_reviews(hut: Hut) -> list[ReviewOut]:
    """All visible reviews of the hut (Mangrove + refuges.info), newest first."""
    blacklisted = set(ReviewBlacklist.objects.values_list("signature", flat=True))
    subject = subject_for_hut(hut)
    dtos = [serialize_review(item) for item in _visible_items(subject, blacklisted)]
    dtos.extend(_refuge_reviews(hut, blacklisted))
    dtos.sort(key=lambda review: review.created, reverse=True)
    return dtos


def list_reviews(hut: Hut, limit: int, offset: int) -> ReviewsEnvelope:
    """The hut's visible reviews, locally paginated across both sources."""
    visible = visible_reviews(hut)
    page = visible[offset : offset + limit]
    return ReviewsEnvelope(
        data=page,
        count=len(visible),
        license=LICENSE,
        attribution=ATTRIBUTION,
    )


def _summarize(slug: str, reviews: list[ReviewOut]) -> ReviewSummaryOut:
    """Locally computed aggregate over the merged visible list (design D6)."""
    ratings = [r.rating for r in reviews if r.rating is not None]
    opinions = [r for r in reviews if r.opinion is not None]
    return ReviewSummaryOut(
        slug=slug,
        count=len(reviews),
        rating_count=len(ratings),
        rating_mean=round(statistics.fmean(ratings), 1) if ratings else None,
        positive_count=sum(1 for rating in ratings if rating > 50),
        opinion_count=len(opinions),
    )


def summary_for_hut(hut: Hut) -> ReviewSummaryOut:
    return _summarize(hut.slug, visible_reviews(hut))


def batch_summary(slugs: list[str]) -> BatchSummaryEnvelope:
    """One aggregate per slug (≤50, canonicalized: sorted, deduplicated)."""
    canonical = sorted({slug.strip() for slug in slugs if slug.strip()})
    summaries = [
        _summarize(hut.slug, visible_reviews(hut))
        for hut in Hut.objects.filter(
            is_active=True, is_public=True, slug__in=canonical
        ).only("slug", "location", "name")
    ]
    known = {s.slug for s in summaries}
    summaries.extend(
        ReviewSummaryOut(
            slug=slug,
            count=0,
            rating_count=0,
            rating_mean=None,
            positive_count=0,
            opinion_count=0,
        )
        for slug in canonical
        if slug not in known
    )
    summaries.sort(key=lambda s: s.slug)
    return BatchSummaryEnvelope(data=summaries, count=len(summaries))


def hut_for_review_name(name: str) -> Hut | None:
    """The public hut whose resolved review name is ``name`` (my-reviews)."""
    pinned = HutReviewSubject.objects.filter(name=name).select_related("hut").first()
    if pinned is not None and pinned.hut.is_active and pinned.hut.is_public:
        return pinned.hut
    from server.apps.huts.models import HutSource

    osm = (
        HutSource.objects.filter(
            hut__is_active=True,
            hut__is_public=True,
            organization__slug="osm",
            is_current=True,
            name=name,
        )
        .select_related("hut")
        .first()
    )
    if osm is not None:
        return osm.hut
    return (
        Hut.objects.filter(is_active=True, is_public=True, name=name)
        .only("slug", "location", "name")
        .first()
    )


def my_reviews(user: t.Any) -> list[MyReviewOut]:
    """The caller's reviews (upstream kid listing) with hut annotation."""
    key = ReviewerKey.objects.filter(user=user).first()
    if key is None:
        return []
    response = client().list_reviews_by_kid(key.kid)
    items = [i for i in response.reviews if i.payload.action is None]
    items.sort(key=lambda i: i.payload.iat, reverse=True)
    out: list[MyReviewOut] = []
    for item in items:
        base = serialize_review(item)
        subject = parse_geo_subject(item.payload.sub)
        hut_slug: str | None = None
        if subject is not None:
            hut = hut_for_review_name(subject.q)
            hut_slug = hut.slug if hut is not None else None
        out.append(MyReviewOut(**base.model_dump(), hut_slug=hut_slug))
    return out


# ── ownership / target checks (design D4/D5) ─────────────────────────


def owns_review(user: t.Any, key: ReviewerKey, signature: str) -> bool:
    """Log-first ownership; upstream kid fallback for foreign keys."""
    if SubmittedReview.objects.filter(user=user, signature=signature).exists():
        return True
    item = client().review(signature)
    if item is None:
        return False
    return "".join(item.kid.split()) == key.kid


def target_belongs_to_hut(hut: Hut, signature: str) -> bool:
    """The targeted review's subject matches the hut in the path (404 gate)."""
    subject = subject_for_hut(hut)
    row = SubmittedReview.objects.filter(signature=signature).first()
    if row is not None:
        return row.subject == subject or subject_geo_matches(row.subject, subject)
    item = client().review(signature)
    if item is None:
        return False
    target = item.original_sub or item.payload.sub
    return target == subject or subject_geo_matches(target, subject)


def _refuse_foreign_target(hut: Hut, signature: str) -> None:
    if not target_belongs_to_hut(hut, signature):
        msg = "Review not found for this hut."
        raise_not_found(msg)


# ── write services ───────────────────────────────────────────────────


def _relay(
    user: t.Any, hut: Hut, subject: str, action: str, jwt: str, target: str
) -> str:
    """Log pending → relay → mark accepted/failed; returns the signature."""
    signature = signing.jwt_signature(jwt)
    row = SubmittedReview.objects.create(
        user=user,
        hut_slug=hut.slug,
        subject=subject,
        action=action,
        state=SubmittedReview.State.pending,
        iat=timezone.now(),
        signature=signature,
        target_signature=target,
        jwt=jwt,
    )
    try:
        client().submit(jwt)
    except UpstreamRejected as exc:
        # Idempotent delete: an already-deleted target refuses the action —
        # that IS the success state (design D4 / spike finding 3).
        if action == SubmittedReview.Action.delete:
            row.state = SubmittedReview.State.accepted
            row.save(update_fields=["state"])
            logger.info("reviews_delete_idempotent", signature=signature[:16])
            return signature
        row.state = SubmittedReview.State.failed
        row.save(update_fields=["state"])
        raise _upstream_rejected() from exc
    except UpstreamUnavailable as exc:
        row.state = SubmittedReview.State.failed
        row.save(update_fields=["state"])
        raise _upstream_unavailable() from exc
    row.state = SubmittedReview.State.accepted
    row.save(update_fields=["state"])
    return signature


def _upstream_unavailable() -> APIError:
    return APIError(
        {
            "code": ErrorCode.service_unavailable,
            "detail": "The review service is temporarily unavailable. Please retry later.",
        },
        status_code=HTTPStatus.SERVICE_UNAVAILABLE,
    )


def _upstream_rejected() -> APIError:
    return APIError(
        {
            "code": ErrorCode.service_unavailable,
            "detail": "The review service rejected the submission.",
        },
        status_code=HTTPStatus.SERVICE_UNAVAILABLE,
    )


def submit_review(
    user: t.Any, hut: Hut, dto: ReviewSubmitIn, language: str
) -> ReviewOut:
    """Validate → pin name → enrich → sign → relay → cache-merge."""
    enforce_enabled()
    key, profile = get_or_mint_key(user)
    enforce_quota(user, "submit")
    name = pin_review_name(hut)
    subject = build_geo_subject(hut.location.y, hut.location.x, name)
    metadata: dict[str, t.Any] = {
        "nickname": dto.nickname or profile.nickname,
        "client_id": settings.MANGROVE_CLIENT_ID,
        "license": LICENSE,
        "language": dto.language or profile.language or language,
    }
    if dto.experience_context is not None:
        metadata["experience_context"] = dto.experience_context
    if dto.is_personal_experience:
        metadata["is_personal_experience"] = True
    if dto.is_affiliated:
        metadata["is_affiliated"] = True
    osm_id = osm_id_for_hut(hut)
    if osm_id:
        metadata["osm_id"] = osm_id
    images = (
        [img.model_dump(exclude_none=True) for img in dto.images]
        if dto.images
        else None
    )
    jwt = signing.build_review_jwt(
        key.kid,
        _decrypt_key_jwk(key),
        subject=subject,
        rating=dto.rating,
        opinion=dto.opinion,
        images=images,
        metadata=metadata,
    )
    _relay(user, hut, subject, SubmittedReview.Action.review, jwt, target="")
    _merge_into_cache(subject, _item_from_own_jwt(jwt, ""))
    return ReviewOut(
        signature=signing.jwt_signature(jwt),
        rating=dto.rating,
        opinion=dto.opinion,
        nickname=metadata["nickname"],
        language=_str_or_none(metadata.get("language")),
        experience_context=dto.experience_context,
        is_personal_experience=bool(dto.is_personal_experience),
        is_affiliated=bool(dto.is_affiliated),
        images=[
            ReviewImageOut(src=img.src, label=img.label) for img in (dto.images or [])
        ],
        created=timezone.now().isoformat(),
        source="mangrove",
        license=LICENSE,
        link=None,
    )


def edit_review(user: t.Any, hut: Hut, signature: str, dto: ReviewEditIn) -> ReviewOut:
    """Ownership + hut gate → signed ``edit`` action (design D5)."""
    enforce_enabled()
    key, _profile = get_or_mint_key(user)
    _refuse_foreign_target(hut, signature)
    if not owns_review(user, key, signature):
        raise _not_owner()
    enforce_quota(user, "edit")
    subject = subject_for_hut(hut)
    jwt = signing.build_action_jwt(
        key.kid,
        _decrypt_key_jwk(key),
        action="edit",
        target_signature=signature,
        rating=dto.rating,
        opinion=dto.opinion,
    )
    _relay(user, hut, subject, SubmittedReview.Action.edit, jwt, target=signature)
    _update_cached_item(subject, signature, dto.rating, dto.opinion)
    return ReviewOut(
        signature=signature,
        rating=dto.rating,
        opinion=dto.opinion,
        nickname=None,
        language=None,
        experience_context=None,
        is_personal_experience=False,
        is_affiliated=False,
        images=[],
        created=timezone.now().isoformat(),
        source="mangrove",
        license=LICENSE,
        link=None,
    )


def delete_review(user: t.Any, hut: Hut, signature: str) -> None:
    """Ownership + hut gate → signed ``delete`` action (idempotent)."""
    enforce_enabled()
    key, _profile = get_or_mint_key(user)
    _refuse_foreign_target(hut, signature)
    if not owns_review(user, key, signature):
        raise _not_owner()
    enforce_quota(user, "edit")
    subject = subject_for_hut(hut)
    jwt = signing.build_action_jwt(
        key.kid,
        _decrypt_key_jwk(key),
        action="delete",
        target_signature=signature,
    )
    _relay(user, hut, subject, SubmittedReview.Action.delete, jwt, target=signature)
    _remove_cached_item(subject, signature)


def report_review(
    user: t.Any, hut: Hut, signature: str, dto: ReviewReportIn
) -> ReportOut:
    """Hut gate (no ownership) → signed ``report_abuse`` action."""
    enforce_enabled()
    key, _profile = get_or_mint_key(user)
    _refuse_foreign_target(hut, signature)
    subject = subject_for_hut(hut)
    jwt = signing.build_action_jwt(
        key.kid,
        _decrypt_key_jwk(key),
        action="report_abuse",
        target_signature=signature,
        opinion=dto.opinion,
    )
    _relay(
        user, hut, subject, SubmittedReview.Action.report_abuse, jwt, target=signature
    )
    return ReportOut(status="reported")


def reply_review(
    user: t.Any, hut: Hut, signature: str, dto: ReviewReplyIn
) -> ReviewOut:
    """Reply to a review: a signed review with an ``urn:maresi`` subject."""
    enforce_enabled()
    key, profile = get_or_mint_key(user)
    _refuse_foreign_target(hut, signature)
    enforce_quota(user, "submit")
    maresi = f"urn:maresi:{signature}"
    metadata: dict[str, t.Any] = {
        "nickname": profile.nickname,
        "client_id": settings.MANGROVE_CLIENT_ID,
        "license": LICENSE,
    }
    jwt = signing.build_review_jwt(
        key.kid,
        _decrypt_key_jwk(key),
        subject=maresi,
        rating=dto.rating,
        opinion=dto.opinion,
        images=None,
        metadata=metadata,
    )
    _relay(user, hut, maresi, SubmittedReview.Action.review, jwt, target=signature)
    cache.delete(_replies_cache_key(signature))
    return ReviewOut(
        signature=signing.jwt_signature(jwt),
        rating=dto.rating,
        opinion=dto.opinion,
        nickname=metadata["nickname"],
        language=None,
        experience_context=None,
        is_personal_experience=False,
        is_affiliated=False,
        images=[],
        created=timezone.now().isoformat(),
        source="mangrove",
        license=LICENSE,
        link=None,
    )


def list_replies(hut: Hut, signature: str) -> ReviewsEnvelope:
    """Replies to one review (``urn:maresi`` listing, cached per signature)."""
    _refuse_foreign_target(hut, signature)
    maresi = f"urn:maresi:{signature}"
    key = _replies_cache_key(signature)
    cached = cache.get(key)
    if cached is not None:
        items = [ReviewItem.model_validate(item) for item in cached]
    else:
        try:
            response = client().list_reviews(maresi)
        except UpstreamUnavailable as exc:
            raise _upstream_unavailable() from exc
        items = [item for item in response.reviews if item.payload.action is None]
        cache.set(key, [item.model_dump() for item in items], _LIST_TTL)
    blacklisted = set(ReviewBlacklist.objects.values_list("signature", flat=True))
    visible = [item for item in items if item.signature not in blacklisted]
    visible.sort(key=lambda item: item.payload.iat, reverse=True)
    return ReviewsEnvelope(
        data=[serialize_review(item) for item in visible],
        count=len(visible),
        license=LICENSE,
        attribution=ATTRIBUTION,
    )


def create_merge_request(
    user: t.Any, hut: Hut, target: str, note: str, link: str
) -> ReviewMergeRequest:
    """File a merge request for staff (admin files equivalence later)."""
    return ReviewMergeRequest.objects.create(
        hut=hut, target=target, note=note, link=link, created_by=user
    )


def _not_owner() -> APIError:
    return APIError(
        {
            "code": ErrorCode.insufficient_permission,
            "detail": "This review belongs to another reviewer.",
        },
        status_code=HTTPStatus.FORBIDDEN,
    )

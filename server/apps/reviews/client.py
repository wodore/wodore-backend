"""The only code path to api.mangrove.reviews (openspec: reviews-mangrove D2).

* ``subject_for_hut`` — the deterministic hut subject recipe (D1).
* ``subject_geo_matches`` — upstream's geo rule, used as the local
  anti-injection filter (D6): normalized-``q`` equality AND coordinates
  within the sum of both ``u`` radii. Verified live 2026-11-08: ``q``
  matches case- and punctuation-insensitively (accents do NOT fold);
  local normalization folds conservatively more (case, punctuation,
  accents) so anything it calls equal upstream may conflate.
* ``MangroveClient`` — httpx with timeouts, GET-only bounded retries,
  one structlog event + Sentry span per call (no review PII), defensive
  pydantic parsing pinned to Server API 0.4.1 via recorded fixtures.
"""

import math
import re
import time
import typing as t
import unicodedata
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
import pydantic
import structlog

from django.conf import settings

logger = structlog.get_logger(__name__)

#: Live Mangrove Server API the client is pinned against (fixtures re-
#: recorded on change — see server/apps/reviews/fixtures/mangrove/).
MANGROVE_API_VERSION = "0.4.1"

#: Upstream list default; >3500 is refused upstream, 1000 is the default.
_UPSTREAM_LIST_LIMIT = 1000

_geo_uri_re = re.compile(
    r"^geo:(?P<lat>-?\d+(?:\.\d+)?),(?P<lon>-?\d+(?:\.\d+)?)(?:\?(?P<query>.*))?$"
)


class UpstreamUnavailable(Exception):
    """The Mangrove API is unreachable, slow or answered unparsable data."""


class UpstreamRejected(Exception):
    """The Mangrove API refused a submission (4xx) — reason in ``detail``."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def normalize_q(q: str) -> str:
    """Normalize a geo ``q`` the way upstream might (conservatively).

    Case- and punctuation-insensitive per the live API (2026-11-08
    spike); accents are folded too — upstream did NOT fold accents in
    the probe, but treating folded-equal as equal keeps the uniqueness
    check on the safe side (it may over-report, never under-report).
    """
    decomposed = unicodedata.normalize("NFKD", q.casefold())
    return "".join(ch for ch in decomposed if ch.isalnum())


class GeoSubject(t.NamedTuple):
    """Parsed ``geo:`` subject URI."""

    lat: float
    lon: float
    q: str
    u: int


def parse_geo_subject(subject: str) -> GeoSubject | None:
    """Parse a ``geo:lat,lon?q=…&u=…`` URI; ``None`` when not geo-shaped."""
    match = _geo_uri_re.match(subject)
    if match is None:
        return None
    query = parse_qs(match.group("query") or "")
    q_values = query.get("q", [])
    u_values = query.get("u", [])
    if not q_values:
        return None
    try:
        u = int(u_values[0]) if u_values else 0
    except ValueError:
        u = 0
    return GeoSubject(
        lat=float(match.group("lat")),
        lon=float(match.group("lon")),
        q=q_values[0],
        u=u,
    )


def subject_for_hut(hut: "t.Any") -> str:
    """The deterministic Mangrove subject of a hut (design D1).

    ``geo:{lat:.6f},{lon:.6f}?q={slug}&u={u}`` — a pure function of the
    hut row; byte-stable for an unchanged row, multilingual-proof.
    """
    location = hut.location
    return "geo:{:.6f},{:.6f}?{}&u={}".format(
        location.y,
        location.x,
        urlencode({"q": hut.slug}),
        settings.MANGROVE_U_RADIUS,
    )


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in meters (WGS84)."""
    radius = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(a))


def subject_geo_matches(candidate: str, reference: str) -> bool:
    """Would upstream consider ``candidate`` a review of ``reference``?

    Upstream rule (live-verified): same ``q`` after normalization AND
    coordinates within the SUM of both ``u`` radii. Wodore-authored
    subjects always carry ``q``; candidates without ``q`` (which match
    on location alone upstream) are rejected here on purpose — the
    anti-injection filter (design D6).
    """
    cand = parse_geo_subject(candidate)
    ref = parse_geo_subject(reference)
    if cand is None or ref is None:
        return False
    if normalize_q(cand.q) != normalize_q(ref.q):
        return False
    distance = _haversine_m(cand.lat, cand.lon, ref.lat, ref.lon)
    return distance <= cand.u + ref.u


# ── Upstream payload models (pinned to 0.4.1 via fixtures) ───────────


class ReviewImagePayload(pydantic.BaseModel):
    """MaReSt ``images[]`` item."""

    model_config = pydantic.ConfigDict(extra="ignore")

    src: str
    label: str | None = None


class ReviewPayload(pydantic.BaseModel):
    """MaReSt review claims set (``payload`` of a listed review)."""

    model_config = pydantic.ConfigDict(extra="ignore")

    iat: int
    sub: str
    rating: int | None = None
    opinion: str | None = None
    action: str | None = None
    images: list[ReviewImagePayload] | None = None
    metadata: dict[str, t.Any] | None = None


class ReviewItem(pydantic.BaseModel):
    """One review as returned by ``GET /reviews`` / ``GET /geo`` (0.4.1)."""

    model_config = pydantic.ConfigDict(extra="ignore")

    jwt: str
    kid: str
    payload: ReviewPayload
    signature: str
    original_sub: str | None = None


class ReviewsResponse(pydantic.BaseModel):
    """``GET /reviews`` response envelope (0.4.1)."""

    model_config = pydantic.ConfigDict(extra="ignore")

    reviews: list[ReviewItem]
    issuers: dict[str, t.Any] | None = None
    maresi_subjects: dict[str, t.Any] | None = None


class IssuerStats(pydantic.BaseModel):
    """``GET /issuer/{pem}`` response (0.4.1)."""

    model_config = pydantic.ConfigDict(extra="ignore")

    count: int
    credibility: float | None = None


class SubjectAggregate(pydantic.BaseModel):
    """``GET /subject/{sub}`` / ``POST /batch`` entry (0.4.1).

    ``quality`` semantics are undocumented upstream — Wodore computes
    aggregates locally (design D6); the model exists for contract
    pinning only.
    """

    model_config = pydantic.ConfigDict(extra="ignore")

    sub: str
    quality: int | None = None
    count: int
    opinion_count: int
    positive_count: int
    confirmed_count: int


def _parse_model(model_cls: type[pydantic.BaseModel], data: t.Any) -> t.Any:
    """Defensive parse: drift degrades to UpstreamUnavailable, not 500."""
    try:
        return model_cls.model_validate(data)
    except pydantic.ValidationError as exc:
        raise UpstreamUnavailable(
            f"upstream response no longer matches the pinned {MANGROVE_API_VERSION} "
            f"contract for {model_cls.__name__}: {exc.error_count()} error(s)"
        ) from exc


class MangroveClient:
    """httpx client for the Original Mangrove Server (the only one)."""

    def __init__(
        self,
        base_url: str | None = None,
        timeout: httpx.Timeout | None = None,
    ) -> None:
        self._base_url = base_url or settings.MANGROVE_API_BASE_URL
        self._timeout = timeout or httpx.Timeout(
            settings.MANGROVE_TIMEOUT_READ,
            connect=settings.MANGROVE_TIMEOUT_CONNECT,
        )

    # ── plumbing ─────────────────────────────────────────────────────

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str | int] | None = None,
        content: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """One request: timeouts, GET-only retries, logging, tracing.

        Raises:
            UpstreamUnavailable: infra failures after the retry budget.
            UpstreamRejected: upstream 4xx with its reason.
        """
        retriable = method == "GET"
        attempts = 1 + (settings.MANGROVE_GET_RETRIES if retriable else 0)
        last_error: Exception | None = None
        with httpx.Client(base_url=self._base_url, timeout=self._timeout) as client:
            for attempt in range(attempts):
                started = time.monotonic()
                try:
                    with structlog.contextvars.bound_contextvars(
                        mangrove_path=path, mangrove_attempt=attempt
                    ):
                        span = sentry_span(path)
                        try:
                            response = client.request(
                                method,
                                path,
                                params=params,
                                content=content,
                                headers=headers,
                            )
                        finally:
                            span.finish()
                    duration_ms = int((time.monotonic() - started) * 1000)
                    if response.status_code >= 500:
                        last_error = UpstreamUnavailable(
                            f"upstream {response.status_code} on {path}"
                        )
                        logger.info(
                            "mangrove_request",
                            method=method,
                            path=path,
                            status=response.status_code,
                            duration_ms=duration_ms,
                            attempt=attempt,
                        )
                        if attempt + 1 < attempts:
                            time.sleep(0.5 * (2**attempt))
                            continue
                        raise last_error
                    logger.info(
                        "mangrove_request",
                        method=method,
                        path=path,
                        status=response.status_code,
                        duration_ms=duration_ms,
                        attempt=attempt,
                    )
                    if response.status_code >= 400:
                        # 4xx: definitive rejection — body to logs, never
                        # verbatim to clients (design D2).
                        logger.warning(
                            "mangrove_rejected",
                            method=method,
                            path=path,
                            status=response.status_code,
                            body=response.text[:500],
                        )
                        raise UpstreamRejected(response.text[:200])
                    return response
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    last_error = exc
                    logger.info(
                        "mangrove_request",
                        method=method,
                        path=path,
                        status="transport-error",
                        error=type(exc).__name__,
                        attempt=attempt,
                    )
                    if attempt + 1 < attempts:
                        time.sleep(0.5 * (2**attempt))
                        continue
        raise UpstreamUnavailable(f"upstream unreachable on {path}: {last_error}")

    # ── API surface (0.4.1) ──────────────────────────────────────────

    def list_reviews(self, subject: str) -> ReviewsResponse:
        """Reviews of a subject (geo/equivalence matching upstream-side)."""
        response = self._request(
            "GET",
            "/reviews",
            params={"sub": subject, "limit": _UPSTREAM_LIST_LIMIT},
        )
        return t.cast(ReviewsResponse, _parse_model(ReviewsResponse, response.json()))

    def list_reviews_by_kid(self, kid_pem: str) -> ReviewsResponse:
        """All reviews of one issuer identity."""
        response = self._request("GET", "/reviews", params={"kid": kid_pem})
        return t.cast(ReviewsResponse, _parse_model(ReviewsResponse, response.json()))

    def review(self, signature: str) -> ReviewItem | None:
        """One review by signature; ``None`` when upstream 404s."""
        try:
            response = self._request("GET", f"/review/{signature}")
        except UpstreamRejected:
            return None
        return t.cast(ReviewItem, _parse_model(ReviewItem, response.json()))

    def issuer(self, pem: str) -> IssuerStats | None:
        """Issuer aggregate; ``None`` when upstream 404s."""
        try:
            response = self._request("GET", f"/issuer/{pem}")
        except UpstreamRejected:
            return None
        return t.cast(IssuerStats, _parse_model(IssuerStats, response.json()))

    def submit(self, jwt: str) -> None:
        """Relay a signed JWT via ``POST /submit`` (text/plain body).

        Never retried — a timeout fails fast (a re-submit could
        duplicate). The response carries no signature; the caller
        derives it (``signing.jwt_signature``).
        """
        self._request(
            "POST",
            "/submit",
            content=jwt,
            headers={"Content-Type": "text/plain"},
        )


def sentry_span(path: str) -> "t.Any":
    """Sentry span around one upstream call (no-op without Sentry)."""
    try:
        import sentry_sdk
    except ImportError:
        return _NullSpan()
    return sentry_sdk.start_span(op="mangrove.request", description=path)


class _NullSpan:
    """Span stand-in when sentry-sdk is absent."""

    def finish(self) -> None:
        return None


def urljoin_base() -> str:
    """The configured upstream base (for logs/admin)."""
    return urlparse(settings.MANGROVE_API_BASE_URL).geturl()

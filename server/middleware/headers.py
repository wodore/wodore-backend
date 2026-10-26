"""
Middleware for adding environment and SEO-related headers.
"""

import re
import typing as t

from django.conf import settings
from django.http import HttpRequest, HttpResponse

# The whole llms.txt family: the bare root, every settings-driven
# /llms.<lang>.txt variant, AND the permanent-redirect responses for
# unknown spellings (server/urls.py routes the catch-all to
# llms_txt_redirect) — all of them are language-fixed per URL, so none
# of them may carry a negotiation Vary.
_LLMS_PATH_RE = re.compile(r"^/llms(?:\.[^/]+)?\.txt$")

# Public API (/v1) CDN cache policy (see ApiCdnCacheMiddleware):
_API_PATH_PREFIX = "/v1/"
#: Default TTL for anonymous public-API reads (one hour, browser+CDN).
_PUBLIC_API_CACHE_CONTROL = "public, max-age=3600"
#: Non-2xx anonymous /v1 responses are never cacheable: the CDN keys its
#: cache by URL, so one cached error or redirect would become the single
#: variant served to every client. Unstamped, the CDN zone default
#: (30 days) would apply anyway — so stamp ``no-store`` explicitly.
_ERROR_CACHE_CONTROL = "no-store"
#: Authenticated API responses are personal — never cacheable anywhere.
_PRIVATE_API_CACHE_CONTROL = "private, no-store"
#: Origin-independent CORS allowance for anonymous public-API reads.
#: Security: the fetch spec forbids credentialed use of a wildcard
#: Access-Control-Allow-Origin (browsers hard-block `*` + credentials),
#: and the middleware strips any Access-Control-Allow-Credentials header
#: before stamping this value — a credentialed cross-origin read of these
#: public, user-independent responses is therefore impossible by
#: construction. The wildcard is what makes the response body+headers
#: origin-independent, which BunnyCDN's URL-keyed single-variant cache
#: requires (per-origin ACAO cannot survive it).
_WILDCARD_ORIGIN = "*"
#: Bunny cache-purge tag family for the public API: the broad ``api`` tag
#: plus an app-specific ``api:<app>`` (first path segment after ``/v1/``,
#: extension stripped). Space-separated multi-tag values are Bunny's
#: CDN-Tag format; a purge targets one tag via the wildcard form
#: ``* api:<app> *`` (taxonomy: _work/261026_cdn_tags.md).
_API_CDN_TAG = "api"


class EnvironmentHeadersMiddleware:
    """
    Middleware that adds environment identification header to all responses.

    Headers added:
        X-Environment: production|staging|development - Identify the environment
    """

    def __init__(self, get_response: t.Callable[[HttpRequest], HttpResponse]) -> None:
        """
        Initialize the middleware.

        Args:
            get_response: Next middleware or view in the chain
        """
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """
        Process the request and add headers to the response.

        Args:
            request: The HTTP request object

        Returns:
            HTTP response with environment header added
        """
        response = self.get_response(request)

        # Add X-Environment header to identify environment
        environment = getattr(settings, "ENVIRONMENT", "unknown")
        response["X-Environment"] = environment

        return response


class LlmsTxtCacheMiddleware:
    """
    Middleware that makes the llms.txt documents safely CDN-cacheable.

    ``django.middleware.locale.LocaleMiddleware`` negotiates the active
    language from Accept-Language and stamps ``Vary: Accept-Language``
    onto every response it processes — including the llms.txt
    documents, whose language is fixed by URL (there is nothing to
    negotiate). The CDN does not vary its cache on Accept-Language, so
    that header would at best split caches and at worst make the
    responses look negotiable when they are not.

    Registered BEFORE LocaleMiddleware (outer in the response phase),
    this middleware therefore strips the Vary header again for exactly
    the llms.txt paths — every other response keeps it.

    Headers affected:
        Vary - removed on /llms.txt, its per-language variants and
        their unknown-spelling redirects
    """

    def __init__(self, get_response: t.Callable[[HttpRequest], HttpResponse]) -> None:
        """
        Initialize the middleware.

        Args:
            get_response: Next middleware or view in the chain
        """
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """
        Process the request and fix the Vary header for llms.txt paths.

        Args:
            request: The HTTP request object

        Returns:
            HTTP response without a Vary header on llms.txt paths
        """
        response = self.get_response(request)

        if _LLMS_PATH_RE.fullmatch(request.path):
            response.headers.pop("Vary", None)

        return response


class ApiCdnCacheMiddleware:
    """
    Auth-state-aware CORS + Cache-Control headers for the public API.

    The frontend routes all unauthenticated GETs through a BunnyCDN host
    (``hub.cdn.stg.wodore.com`` / ``hub.cdn.wodore.com``); Bearer-authenticated
    requests always go direct to the API host. Bunny keys its cache by URL
    and collapses ``Vary`` (including corsheaders' ``Vary: Origin``), so the
    FIRST response filled for a URL becomes the single cache variant served
    to every client — including browsers that sent an ``Origin`` header. With
    corsheaders' per-origin ``Access-Control-Allow-Origin`` that variant
    either carries a foreign origin or none at all, and browsers reject it.

    This middleware makes the public API cache-correct without any CDN edge
    rules, for exactly the ``/v1/`` paths that go through the CDN:

    * Anonymous GET/HEAD (no ``Authorization`` request header):
      ``Access-Control-Allow-Origin`` is REPLACED with ``*`` (origin-
      independent ⇒ one cache variant serves every browser; safe because
      these responses are public, user-independent — API auth is purely
      Bearer — and never credentialed: any ``Access-Control-Allow-
      Credentials`` header is stripped alongside, and the fetch spec
      forbids credentialed use of a wildcard ACAO anyway). A default
      ``Cache-Control: public, max-age=3600`` — on 2xx responses only —
      makes the CDN honor a bounded TTL instead of its zone default
      (30 days). Every other status (errors, redirects) is stamped
      ``no-store`` so a cached 404/429/500 can never become the CDN's
      variant for the URL; 304s are deliberately unstamped (a
      revalidation owns no TTL — the stored 200 does). ``/v1/version``
      carries its short ``max-age=300`` from the view itself
      (``@modify(headers=cache_headers(VERSION_TTL))``, see
      ``server/apps/utils/api.py``) — the only-if-unset rule lets the
      view's header win over this default.
    * Authenticated requests (any method, ``Authorization`` present):
      ``Cache-Control: private, no-store`` — the safety net. If a frontend
      bug ever routes Bearer traffic through the CDN host, Bunny honors
      origin cache headers, so personalized responses pass through
      uncached — no cross-user leak. CORS is left exactly as corsheaders
      produced it (per-origin).
    * ``Cache-Control`` is only ever set when the response does not carry
      one yet — endpoints deliberately overriding their TTL (sitemaps,
      SVG redirects, ETag revalidation endpoints) always win.
    * 2xx anonymous reads also carry ``CDN-Tag: api api:<app>`` (Bunny
      tag-based purging: flush one app or the whole API without touching
      untagged surfaces — media, static; taxonomy in
      ``_work/261026_cdn_tags.md``). Errors, 304s and authenticated
      responses stay untagged — only what the CDN actually stores owns
      a purge tag.
    * OPTIONS (preflights belong to corsheaders) and anonymous non-GET/HEAD
      requests (POST etc. are never CDN-cached) are left untouched.

    Registered BEFORE ``corsheaders.middleware.CorsMiddleware`` — outer in
    the response phase — so it runs after corsheaders and can replace its
    per-origin output; corsheaders unconditionally overwrites
    ``Access-Control-Allow-Origin`` for allowed origins, so a position below
    corsheaders would have its ``*`` clobbered again (same trick as
    ``LlmsTxtCacheMiddleware`` above). corsheaders' ``Vary: Origin`` is left
    in place: harmless under ``*`` and ignored by the CDN anyway.
    """

    def __init__(self, get_response: t.Callable[[HttpRequest], HttpResponse]) -> None:
        """
        Initialize the middleware.

        Args:
            get_response: Next middleware or view in the chain
        """
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """
        Process the request and stamp CDN cache policy on /v1 responses.

        Args:
            request: The HTTP request object

        Returns:
            HTTP response with auth-state-aware CORS/Cache-Control headers
        """
        response = self.get_response(request)

        if not request.path_info.startswith(_API_PATH_PREFIX):
            return response

        if request.method == "OPTIONS":
            # Preflights belong to corsheaders; the CDN passes OPTIONS
            # through uncached. Non-preflight OPTIONS stay untouched too.
            return response

        if request.headers.get("Authorization"):
            # Authenticated request — must never be cached anywhere, even
            # if a frontend bug sends it through the CDN host. CORS headers
            # stay per-origin as corsheaders produced them.
            _set_cache_control_if_unset(response, _PRIVATE_API_CACHE_CONTROL)
            return response

        if request.method in ("GET", "HEAD"):
            # Anonymous public read: flatten CORS to the origin-independent
            # wildcard (replace, never append) so a single CDN cache variant
            # serves every browser origin, and stamp a bounded default TTL.
            # The CORS flattening applies to EVERY status: browsers must
            # stay able to read error bodies cross-origin, and the CDN's
            # single variant must be origin-independent whatever the
            # upstream outcome. The wildcard never rides with
            # credentials: the fetch spec forbids credentialed use of
            # `ACAO: *`, and any Allow-Credentials header corsheaders
            # stamped is stripped so the combination cannot occur even
            # if CORS_ALLOW_CREDENTIALS were ever enabled (we run after
            # corsheaders in the response phase — this is the final
            # word).
            response.headers.pop("Access-Control-Allow-Origin", None)
            response.headers.pop("Access-Control-Allow-Credentials", None)
            response["Access-Control-Allow-Origin"] = _WILDCARD_ORIGIN
            if 200 <= response.status_code < 300:
                _set_cache_control_if_unset(response, _PUBLIC_API_CACHE_CONTROL)
                _set_cdn_tag_if_unset(response, _api_cdn_tag(request.path_info))
            elif response.status_code != 304:
                # Errors and redirects must never seed the URL-keyed CDN
                # cache: the first cached variant is served to every
                # client, so one 404/429/500 would masquerade as the
                # endpoint for the full TTL. 304s are exempt — a
                # revalidation response owns no TTL of its own (the
                # stored 200 does) and endpoints issuing them set their
                # own Cache-Control.
                _set_cache_control_if_unset(response, _ERROR_CACHE_CONTROL)

        # Anonymous non-GET/HEAD (POST etc.): the CDN never caches those —
        # leave the response untouched.

        return response


def _set_cache_control_if_unset(response: HttpResponse, value: str) -> None:
    """Set ``Cache-Control`` unless the response already carries one.

    Endpoints may deliberately override their cache TTL — never clobber.

    Args:
        response: The HTTP response to (maybe) stamp
        value: Cache-Control value to set if absent
    """
    if "Cache-Control" not in response.headers:
        response["Cache-Control"] = value


def _api_cdn_tag(path_info: str) -> str:
    """Bunny ``CDN-Tag`` value for a cacheable anonymous /v1 response.

    ``api api:<app>`` (``/v1/huts/...`` → ``api api:huts``), plain ``api``
    when no app segment exists (bare ``/v1/``). The segment's extension
    is stripped (``/v1/openapi.json`` → ``api:openapi``) so the tag set
    stays small and predictable. Untagged surfaces (Django media, static,
    admin — none of which flow through the CDN host) can never be hit by
    a tag purge.

    Args:
        path_info: The request's path (``request.path_info``)

    Returns:
        Space-separated CDN-Tag value for the response
    """
    segment = path_info[len(_API_PATH_PREFIX) :].partition("/")[0]
    app = segment.partition(".")[0]
    if app:
        return f"{_API_CDN_TAG} {_API_CDN_TAG}:{app}"
    return _API_CDN_TAG


def _set_cdn_tag_if_unset(response: HttpResponse, value: str) -> None:
    """Set ``CDN-Tag`` unless the response already carries one.

    Mirrors the Cache-Control only-if-unset rule: an endpoint stamping
    its own purge tag is never clobbered.

    Args:
        response: The HTTP response to (maybe) stamp
        value: CDN-Tag value to set if absent
    """
    if "CDN-Tag" not in response.headers:
        response["CDN-Tag"] = value


class RobotsTagMiddleware:
    """
    Middleware that adds X-Robots-Tag header to prevent search engine indexing.

    Headers added:
        X-Robots-Tag: noindex, nofollow - Prevent search engine indexing

    This is typically used in staging/development environments to prevent
    accidental indexing. Can also be used in production for API-only backends.
    """

    def __init__(self, get_response: t.Callable[[HttpRequest], HttpResponse]) -> None:
        """
        Initialize the middleware.

        Args:
            get_response: Next middleware or view in the chain
        """
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """
        Process the request and add headers to the response.

        Args:
            request: The HTTP request object

        Returns:
            HTTP response with X-Robots-Tag header added
        """
        response = self.get_response(request)

        # Add X-Robots-Tag header to prevent indexing
        response["X-Robots-Tag"] = "noindex, nofollow"

        return response

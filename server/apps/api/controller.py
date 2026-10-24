"""Base controller for all Wodore JSON API endpoints.


Establishes the project-wide error contract on dmr:

    {"code": "<machine readable>", "detail": "<human readable>"}

plus the RFC 9457 problem members ``type``/``title``/``status`` (and
``instance`` where a resource path is identifiable) merged in once, at
the ``to_error`` boundary every dmr error render funnels through
(openspec: api-errors) — see :mod:`server.apps.api.error_codes`.

This is the shape the API-versioning middleware has always used for
version errors (``api_version_conflict`` etc.). The former django-ninja
layer produced ``{"detail": "..."}`` for ``HttpError`` — unifying on the
middleware shape is a deliberate, small contract drift (error bodies
only; status codes unchanged) so every error a client can receive has
one predictable format, documented in the OpenAPI schema via dmr's
``error_model`` mechanism.
"""

import hashlib
import typing
from functools import wraps
from http import HTTPStatus
from typing import Any
from urllib.parse import urlencode

from dmr import APIError, Controller, NewCookie, NewHeader
from dmr.endpoint import Endpoint
from dmr.errors import ErrorType, format_error
from dmr.exceptions import TooManyRequestsError
from dmr.renderers import Renderer
from dmr.serializer import BaseSerializer
from typing_extensions import TypedDict, override

from django.http import Http404, HttpRequest, HttpResponse

from server.apps.api.error_codes import ErrorCode, enrich_problem_details

from .serializer import WodoreSerializer

#: Mirror of dmr's 405 message (``_METHOD_NOT_ALLOWED_MSG``) — kept
#: local because dmr marks it private; format is
#: ``'Method {method} is not allowed, allowed: {allowed}'``.
_METHOD_NOT_ALLOWED_MSG = "Method {method} is not allowed, allowed: {allowed}"


class ErrorDetail(TypedDict, total=False):
    """Error body: ``code`` for clients, ``detail`` for humans.

    RFC 9457 problem members are merged in at the ``to_error``
    boundary on every error (openspec: api-errors): ``type``, ``title``
    and ``status`` always; ``instance`` only for resource-scoped codes
    (``not_found``, ``gone``) where a request path exists.
    """

    code: str
    detail: str

    #: RFC 9457: URI identifying the problem class
    #: (``{BACKEND_DOMAIN}/errors/<code>``).
    type: str
    #: RFC 9457: short human summary from the ErrorCode registry.
    title: str
    #: RFC 9457: the HTTP status code, mirrored as an int.
    status: int
    #: RFC 9457: URI of the affected resource (request path); only
    #: present for resource-scoped codes.
    instance: str


#: Endpoints that answer non-JSON (Markdown, SVG redirects, sitemaps)
#: are plain Django views (``external_path``) and never use this base.
class ApiController(Controller[WodoreSerializer]):
    """Base controller: Wodore error format + common error mapping."""

    error_model = ErrorDetail

    @override
    def format_error(
        self,
        error: str | Exception,
        *,
        loc: str | list[str | int] | None = None,
        error_type: str | ErrorType | None = None,
    ) -> dict[str, str]:
        """Render errors as ``{"code", "detail"}``.

        Validation errors (bad query/body input) map to
        ``code="validation_error"`` and keep the message(s) in
        ``detail`` so clients can show something useful. Throttle
        rejections map to ``code="throttled"`` so clients back off
        instead of blaming their request shape (openspec: api-throttling).
        """
        if isinstance(error, TooManyRequestsError):
            return {
                "code": ErrorCode.throttled,
                "detail": str(error) or "Too many requests.",
            }
        if isinstance(error, str):
            return {"code": ErrorCode.validation_error, "detail": error}
        default = format_error(error, loc=loc, error_type=error_type)
        messages = "; ".join(detail["msg"] for detail in default["detail"])
        rate_limited = any(
            detail.get("type") == str(ErrorType.ratelimit)
            for detail in default["detail"]
            if isinstance(detail, dict)
        )
        return {
            "code": (
                ErrorCode.throttled if rate_limited else ErrorCode.validation_error
            ),
            "detail": messages or str(error),
        }

    @override
    def handle_error(
        self,
        endpoint: Endpoint,
        controller: "Controller[BaseSerializer]",
        exc: Exception,
    ) -> HttpResponse:
        """Map framework-agnostic exceptions to the Wodore error body."""
        if isinstance(exc, Http404):
            return self.to_error(
                {"code": ErrorCode.not_found, "detail": str(exc) or "Not found."},
                status_code=HTTPStatus.NOT_FOUND,
            )
        # APIError (raised by handlers/auth) already carries its payload
        # in format_error shape and has a built-in handler; re-raise it.
        raise exc from None

    @override
    def to_error(
        self,
        raw_data: typing.Any,
        *,
        status_code: HTTPStatus,
        headers: typing.Mapping[str, str] | None = None,
        cookies: typing.Mapping[str, NewCookie] | None = None,
        renderer: Renderer | None = None,
    ) -> HttpResponse:
        """Serialize error bodies with RFC 9457 problem members merged in.

        Every dmr error render funnels through this method — direct
        ``APIError`` raises (``raise_not_found``, auth, query parsing,
        sunset guards), the ``Http404`` mapping above and the global
        handler's ``format_error`` output — so this is the single
        enrichment point (design.md D4): all controllers and the
        plain/GeoJSON views raising our errors inherit without
        per-endpoint work. Non-contract payloads pass through
        untouched; the media type stays ``application/json``.
        """
        request = getattr(self, "request", None)
        return super().to_error(
            enrich_problem_details(
                raw_data,
                status=status_code,
                path=getattr(request, "path", None),
            ),
            status_code=status_code,
            headers=headers,
            cookies=cookies,
            renderer=renderer,
        )

    @override
    def handle_method_not_allowed(self, method: str) -> HttpResponse:
        """405s share the enriched error contract (review finding #2).

        dmr's base implementation renders with the low-level
        ``build_response`` primitive, bypassing ``to_error`` — route it
        through ``to_error`` so the RFC 9457 members are merged in and
        the shared-machinery invariant holds for 405 responses too.
        """
        allowed_methods = sorted(self.api_endpoints.keys())
        return self.to_error(
            self.format_error(
                _METHOD_NOT_ALLOWED_MSG.format(
                    method=repr(method),
                    allowed=repr(allowed_methods),
                ),
                error_type=ErrorType.not_allowed,
            ),
            status_code=HTTPStatus.METHOD_NOT_ALLOWED,
            headers={"Allow": ", ".join(allowed_methods)},
        )


def raise_not_found(detail: str) -> typing.NoReturn:
    """Raise the standard 404 APIError from any handler."""
    raise APIError(
        {"code": ErrorCode.not_found, "detail": detail},
        status_code=HTTPStatus.NOT_FOUND,
    )


def cache_headers(max_age: int) -> dict[str, NewHeader]:
    """``Cache-Control`` header spec for ``@modify(headers=...)``.

    Replaces the former ``@decorate_view(cache_control(max_age=...))``
    ninja idiom — dmr documents and sets the header in one place.
    """
    return {
        "Cache-Control": NewHeader(value=f"public, max-age={max_age}"),
    }


#: ``Cache-Control`` for the SVG redirect endpoints (categories, meteo,
#: symbols): caches may reuse the 302 for a day and keep serving it
#: stale for up to a week while revalidating in the background. The
#: redirect target is content-unique media (re-uploads change the file
#: name), so a briefly stale redirect is cheap — without the short
#: max-age a replaced icon would stay stale for the full window.
REDIRECT_CACHE_CONTROL = "public, max-age=86400, stale-while-revalidate=604800"

#: Revalidate-always caching for evolving documents (api-conventions):
#: stored, but revalidated on every use — one online reload is fresh;
#: offline/origin-down may serve the stored copy for a day.
REVALIDATE_CACHE_CONTROL = "public, max-age=0, must-revalidate, stale-if-error=604800"


def revalidate_headers() -> dict[str, NewHeader]:
    """``Cache-Control`` header spec for ``@modify(headers=...)``."""
    return {"Cache-Control": NewHeader(value=REVALIDATE_CACHE_CONTROL)}


def etag_page(
    version_fn: Any,
    cache_control: str = REVALIDATE_CACHE_CONTROL,
) -> Any:
    """Conditional-request wrapper for collection/detail views.

    Computes a strong ETag from the version function plus every query
    parameter and the resolved API version. ``If-None-Match`` answers
    304 without rendering; otherwise the rendered body is cached keyed
    by the ETag (version-keyed ⇒ self-busting — no time-based page
    cache).

    ``cache_control`` overrides the ``Cache-Control`` header written on
    200 and 304 responses (default: ``REVALIDATE_CACHE_CONTROL``).
    """

    def decorator(view: Any) -> Any:
        @wraps(view)
        def wrapped(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
            version = version_fn(request, **kwargs)
            vary = "|".join(
                (
                    request.path,
                    version,
                    urlencode(sorted(request.GET.items())),
                    getattr(request, "api_version", "") or "",
                )
            )
            etag = f'"{hashlib.sha256(vary.encode()).hexdigest()[:20]}"'
            match = request.headers.get("If-None-Match") == etag
            if match:
                response = HttpResponse(status=HTTPStatus.NOT_MODIFIED)
            else:
                from django.core.cache import cache

                body = cache.get(f"api:doc:{etag}")
                if body is None:
                    response = view(request, *args, **kwargs)
                    if response.status_code == HTTPStatus.OK:
                        cache.set(
                            f"api:doc:{etag}",
                            response.content,
                            timeout=24 * 60 * 60,
                        )
                else:
                    response = HttpResponse(body, content_type="application/json")
            if match or response.status_code == HTTPStatus.OK:
                response.headers["ETag"] = etag
                response.headers["Cache-Control"] = cache_control
            return response

        return wrapped

    return decorator

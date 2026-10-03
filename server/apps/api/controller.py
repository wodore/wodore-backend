"""Base controller for all Wodore JSON API endpoints.


Establishes the project-wide error contract on dmr:

    {"code": "<machine readable>", "detail": "<human readable>"}

This is the shape the API-versioning middleware has always used for
version errors (``api_version_conflict`` etc.). The former django-ninja
layer produced ``{"detail": "..."}`` for ``HttpError`` — unifying on the
middleware shape is a deliberate, small contract drift (error bodies
only; status codes unchanged) so every error a client can receive has
one predictable format, documented in the OpenAPI schema via dmr's
``error_model`` mechanism.
"""

import typing
from http import HTTPStatus

from dmr import APIError, Controller, NewHeader
from dmr.endpoint import Endpoint
from dmr.errors import ErrorType, format_error
from dmr.serializer import BaseSerializer
from typing_extensions import TypedDict, override

from django.http import Http404, HttpResponse

from server.apps.api.error_codes import ErrorCode

from .serializer import WodoreSerializer


class ErrorDetail(TypedDict, total=False):
    """Error body: ``code`` for clients, ``detail`` for humans."""

    code: str
    detail: str


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
        ``detail`` so clients can show something useful.
        """
        if isinstance(error, str):
            return {"code": ErrorCode.validation_error, "detail": error}
        default = format_error(error, loc=loc, error_type=error_type)
        messages = "; ".join(detail["msg"] for detail in default["detail"])
        return {
            "code": ErrorCode.validation_error,
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

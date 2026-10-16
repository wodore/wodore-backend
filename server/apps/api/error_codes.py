"""Shared error codes for the Wodore API error contract.

Every ``APIError`` and error response carries ``{"code", "detail"}``.
One code per HTTP behavioral class the client acts on differently;
the specific reason always lives in ``detail``.

RFC 9457 (Problem Details) alignment (openspec: api-errors): every
error body additionally carries the problem members ``type``,
``title`` and ``status`` — plus ``instance`` where a resource path is
identifiable — derived here from this registry. ``code`` stays a
registered RFC 9457 extension member and ``detail``/media type
(``application/json``) are unchanged, so existing clients (generated
TS pinned to ``code``/``detail``) keep working without migration.

The problem-type URIs built here (``{BACKEND_DOMAIN}/errors/<code>``)
are permanent identifiers (RFC 9457 §3.1.1): they need not be
dereferenceable and must not be recycled even if the public host
moves — only the default template would change, never a code's URI.
"""

from __future__ import annotations

import typing
from enum import StrEnum

from django.conf import settings

if typing.TYPE_CHECKING:
    from http import HTTPStatus


class ErrorCode(StrEnum):
    """Machine-readable error codes — one per client behavior."""

    validation_error = "validation_error"
    throttled = "throttled"
    not_authenticated = "not_authenticated"
    insufficient_permission = "insufficient_permission"
    not_found = "not_found"
    gone = "gone"
    service_unavailable = "service_unavailable"
    #: Emitted by the API-version middleware when the pinned version
    #: is past its sunset date (registered here so the problem-details
    #: enrichment covers it like every other code).
    api_version_sunset = "api_version_sunset"


#: Short human summary per code — RFC 9457 ``title``. Titles MUST NOT
#: vary per occurrence (RFC 9457 §3.1); the specific reason always
#: lives in ``detail``. Completeness is unit-tested (spec: api-errors).
PROBLEM_TITLES: typing.Final[dict[ErrorCode, str]] = {
    ErrorCode.validation_error: "The request input is invalid.",
    ErrorCode.throttled: "Too many requests.",
    ErrorCode.not_authenticated: "Authentication is required.",
    ErrorCode.insufficient_permission: "Insufficient permission.",
    ErrorCode.not_found: "The requested resource was not found.",
    ErrorCode.gone: "The requested resource is gone.",
    ErrorCode.service_unavailable: "The service is temporarily unavailable.",
    ErrorCode.api_version_sunset: "The requested API version is sunset.",
}

#: Codes whose failure is about the addressed resource: these (and
#: only these) carry the RFC 9457 ``instance`` member pointing at the
#: request path. Validation/throttle/auth/version errors are about the
#: request as a whole, not a resource — they omit ``instance``.
INSTANCE_SCOPED_CODES: typing.Final[frozenset[ErrorCode]] = frozenset(
    (
        ErrorCode.not_found,
        ErrorCode.gone,
    )
)


def problem_type_uri(code: ErrorCode) -> str:
    """Stable problem-type URI (RFC 9457 ``type`` member) for a code."""
    origin = settings.BACKEND_DOMAIN.rstrip("/")
    return f"{origin}/errors/{code.value}"


def problem_instance(code: ErrorCode, *, path: str | None) -> str | None:
    """RFC 9457 ``instance`` member for a code, or ``None`` to omit.

    Resource-scoped codes (see ``INSTANCE_SCOPED_CODES``) carry the
    full request path (design.md D3); everything else omits the member.
    """
    if path and code in INSTANCE_SCOPED_CODES:
        return path
    return None


def problem_fields(
    code: ErrorCode,
    *,
    status: int | HTTPStatus,
    instance: str | None = None,
) -> dict[str, str | int]:
    """RFC 9457 problem members for a code + HTTP status.

    Returns ``type``/``title``/``status`` (mirroring the response
    status as an int) and, when given, ``instance``. Merge alongside
    the Wodore ``code``/``detail`` contract members.
    """
    members: dict[str, str | int] = {
        "type": problem_type_uri(code),
        "title": PROBLEM_TITLES[code],
        "status": int(status),
    }
    if instance is not None:
        members["instance"] = instance
    return members


def enrich_problem_details(
    body: typing.Any,
    *,
    status: int | HTTPStatus,
    path: str | None = None,
) -> typing.Any:
    """Merge RFC 9457 problem members into a Wodore error body.

    Single enrichment point for the shared error machinery (design.md
    D4): bodies shaped ``{"code": <ErrorCode>, ...}`` gain
    ``type``/``title``/``status`` (plus ``instance`` for resource-scoped
    codes when a request path is given); any other body — plain dmr
    payloads, non-dicts, foreign codes — passes through unchanged.
    Existing members are never removed or overwritten.
    """
    if not isinstance(body, dict):
        return body
    raw_code = body.get("code")
    if not isinstance(raw_code, str):
        return body
    try:
        code = ErrorCode(raw_code)
    except ValueError:
        return body
    enriched = dict(body)
    enriched.update(
        problem_fields(
            code,
            status=status,
            instance=problem_instance(code, path=path),
        ),
    )
    return enriched

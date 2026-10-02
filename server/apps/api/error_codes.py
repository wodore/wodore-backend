"""Shared error codes for the Wodore API error contract.

Every ``APIError`` and error response carries ``{"code", "detail"}``.
Codes are only as granular as the client's behavioral branching:
one code per distinct action the frontend takes. The specific reason
always lives in ``detail``; granular diagnostics belong in server logs.
"""

from enum import StrEnum


class ErrorCode(StrEnum):
    """Machine-readable error codes — one per client behavior."""

    # 400: the request is malformed (detail explains what)
    validation_error = "validation_error"

    # 400: versioning-specific programming errors
    api_version_conflict = "api_version_conflict"
    api_version_invalid = "api_version_invalid"

    # 401: not logged in / token invalid
    not_authenticated = "not_authenticated"

    # 401/403: logged in but lacking role/scope
    insufficient_permission = "insufficient_permission"

    # 404
    not_found = "not_found"

    # 410: version or endpoint past sunset
    gone = "gone"

    # 500: internal error
    internal_error = "internal_error"

    # 503: external dependency down
    service_unavailable = "service_unavailable"

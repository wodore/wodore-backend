"""Shared error codes for the Wodore API error contract.

Every ``APIError`` and error response carries ``{"code", "detail"}``.
One code per HTTP behavioral class the client acts on differently;
the specific reason always lives in ``detail``.
"""

from enum import StrEnum


class ErrorCode(StrEnum):
    """Machine-readable error codes — one per client behavior."""

    validation_error = "validation_error"
    not_authenticated = "not_authenticated"
    insufficient_permission = "insufficient_permission"
    not_found = "not_found"
    gone = "gone"
    service_unavailable = "service_unavailable"

"""Shared error codes for the Wodore API error contract.

Every ``APIError`` and error response carries ``{"code", "detail"}``.
The codes live here so the frontend can mirror them and branch reliably.
Adding a code: define it here, use ``ErrorCode.xxx`` at the raise site.
"""

from enum import StrEnum


class ErrorCode(StrEnum):
    """Machine-readable error codes (the wire contract)."""

    # Request validation
    validation_error = "validation_error"
    invalid_parameter = "invalid_parameter"
    invalid_field_name = "invalid_field_name"
    invalid_field_type = "invalid_field_type"
    ambiguous_category = "ambiguous_category"

    # Resource errors
    not_found = "not_found"

    # Auth
    not_authenticated = "not_authenticated"
    auth_not_configured = "auth_not_configured"
    insufficient_scope = "insufficient_scope"
    insufficient_permission = "insufficient_permission"
    invalid_token_revoked = "invalid_token_revoked"
    invalid_token_inactive = "invalid_token_inactive"
    invalid_token_expired = "invalid_token_expired"

    # API versioning
    api_version_conflict = "api_version_conflict"
    api_version_invalid = "api_version_invalid"
    api_version_sunset = "api_version_sunset"
    endpoint_sunset = "endpoint_sunset"
    api_snapshot_missing = "api_snapshot_missing"

    # Domain
    booking_service_unavailable = "booking_service_unavailable"

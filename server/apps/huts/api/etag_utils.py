"""
E-Tag utilities for caching hut endpoints.

Generates ETags based on the last modified timestamp across all relevant tables.
"""

import hashlib
from typing import Any

from django.conf import settings
from django.db.models import Max, QuerySet
from django.http import HttpRequest, HttpResponse
from django.utils.http import http_date, parse_http_date_safe

from server.apps.availability.models import AvailabilityStatus
from server.apps.huts.models import Hut
from server.apps.images.models import Image
from server.apps.organizations.models import Organization
from server.apps.owners.models import Owner


def get_last_modified_timestamp(
    *,
    include_huts: bool = True,
    include_organizations: bool = False,
    include_owners: bool = False,
    include_images: bool = False,
    include_availability: bool = False,
    hut_queryset: QuerySet[Hut] | None = None,
) -> float:
    """
    Get the latest modification timestamp across specified tables.

    Args:
        include_huts: Include Hut table
        include_organizations: Include Organization table (for sources)
        include_owners: Include Owner table
        include_images: Include Image table
        include_availability: Include AvailabilityStatus table
        hut_queryset: Optional filtered hut queryset to check (if None, checks all huts)

    Returns:
        Unix timestamp of the latest modification
    """
    timestamps: list[Any] = []

    # Huts table
    if include_huts:
        qs = hut_queryset if hut_queryset is not None else Hut.objects.all()
        hut_modified = qs.aggregate(Max("modified"))["modified__max"]
        if hut_modified:
            timestamps.append(hut_modified.timestamp())

    # Organizations table
    if include_organizations:
        org_modified = Organization.objects.aggregate(Max("modified"))["modified__max"]
        if org_modified:
            timestamps.append(org_modified.timestamp())

    # Owners table
    if include_owners:
        owner_modified = Owner.objects.aggregate(Max("modified"))["modified__max"]
        if owner_modified:
            timestamps.append(owner_modified.timestamp())

    # Images table
    if include_images:
        image_modified = Image.objects.aggregate(Max("modified"))["modified__max"]
        if image_modified:
            timestamps.append(image_modified.timestamp())

    # AvailabilityStatus table
    if include_availability:
        avail_modified = AvailabilityStatus.objects.aggregate(Max("modified"))[
            "modified__max"
        ]
        if avail_modified:
            timestamps.append(avail_modified.timestamp())

    return max(timestamps) if timestamps else 0.0


def generate_etag(
    *,
    include_huts: bool = True,
    include_organizations: bool = False,
    include_owners: bool = False,
    include_images: bool = False,
    include_availability: bool = False,
    hut_queryset: QuerySet[Hut] | None = None,
    additional_keys: list[str] | None = None,
) -> str:
    """
    Generate an ETag based on last modified timestamps.

    Args:
        include_*: Which tables to check for modifications
        hut_queryset: Optional filtered hut queryset
        additional_keys: Additional strings to include in hash (e.g., query parameters)

    Returns:
        ETag string (quoted, e.g., '"abc123"')
    """
    timestamp = get_last_modified_timestamp(
        include_huts=include_huts,
        include_organizations=include_organizations,
        include_owners=include_owners,
        include_images=include_images,
        include_availability=include_availability,
        hut_queryset=hut_queryset,
    )

    # Create hash input
    hash_parts = [str(timestamp)]

    # Include git hash for cache invalidation on code changes
    hash_parts.append(settings.GIT_HASH)

    if additional_keys:
        hash_parts.extend(additional_keys)

    hash_input = "-".join(hash_parts)
    etag_hash = hashlib.md5(hash_input.encode()).hexdigest()

    return f'"{etag_hash}"'


def check_etag_match(request: HttpRequest, etag: str) -> bool:
    """
    Check if the request's If-None-Match header matches the generated ETag.

    Args:
        request: The HTTP request
        etag: The generated ETag

    Returns:
        True if ETags match (resource not modified)
    """
    if_none_match = request.headers.get("If-None-Match")
    if not if_none_match:
        return False

    # Handle multiple ETags in If-None-Match
    request_etags = [tag.strip() for tag in if_none_match.split(",")]
    return etag in request_etags or "*" in request_etags


def get_last_modified_http_date(
    *,
    include_huts: bool = True,
    include_organizations: bool = False,
    include_owners: bool = False,
    include_images: bool = False,
    include_availability: bool = False,
    hut_queryset: QuerySet[Hut] | None = None,
) -> str:
    """
    Get the Last-Modified HTTP header value.

    Returns:
        HTTP date string (e.g., "Mon, 06 Jan 2026 10:30:00 GMT")
    """
    timestamp = get_last_modified_timestamp(
        include_huts=include_huts,
        include_organizations=include_organizations,
        include_owners=include_owners,
        include_images=include_images,
        include_availability=include_availability,
        hut_queryset=hut_queryset,
    )

    return http_date(timestamp)


def check_if_modified_since(request: HttpRequest, last_modified: str) -> bool:
    """
    Check if the resource was modified since the If-Modified-Since header.

    Args:
        request: The HTTP request
        last_modified: Last-Modified HTTP date string

    Returns:
        True if resource was modified (should return full response)
    """
    if_modified_since = request.headers.get("If-Modified-Since")
    if not if_modified_since:
        return True  # No header, assume modified

    # Parse both dates
    client_timestamp = parse_http_date_safe(if_modified_since)
    server_timestamp = parse_http_date_safe(last_modified)

    if client_timestamp is None or server_timestamp is None:
        return True  # Parse error, assume modified

    # If server timestamp is newer, resource was modified
    return server_timestamp > client_timestamp


def set_cache_headers(
    response: HttpResponse,
    etag: str,
    last_modified: str,
    max_age: int = 30,
) -> HttpResponse:
    """
    Set caching headers on the response.

    Args:
        response: The HTTP response
        etag: ETag value
        last_modified: Last-Modified HTTP date
        max_age: Cache-Control max-age in seconds

    Returns:
        Response with headers set
    """
    response["ETag"] = etag
    response["Last-Modified"] = last_modified
    response["Cache-Control"] = f"public, max-age={max_age}"
    return response

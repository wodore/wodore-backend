"""API version registry: date-based contract versioning inside /v1/.

OpenSpec change ``add-api-date-versioning``. One codebase always runs the
newest logic; older client versions are produced by transforms at the edge
(see :mod:`server.apps.apiversions.transforms`). This module is the single
source of truth for versions, their lifecycle status and the registry
content hash that participates in ETags.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

Transform = Callable[[Any], Any]

# Rollout date of the versioning system itself. Every client is effectively
# pinned to this version until the first breaking change registers a newer
# one. Set to the release date of this feature (see design.md D1).
INITIAL_VERSION = "2026-10-01"

# Where the API changelog lives (Link; rel="deprecation" targets).
CHANGELOG_URL = "https://github.com/wodore/wodore-backend/blob/main/CHANGELOG_API.md"


@dataclass(frozen=True)
class EndpointDeprecation:
    """Endpoint-level deprecation (independent of version-level sunset).

    Deprecated operations announce ``Deprecation``/``Sunset``/``Link``
    headers in every API version and are answered with ``410`` after
    ``sunset`` (enforced in :func:`server.apps.apiversions.wrap.wrap_api`).
    """

    announced: date
    sunset: date
    detail: str = ""
    link: str = CHANGELOG_URL

    @property
    def announced_unix(self) -> int:
        return int(
            datetime(
                self.announced.year,
                self.announced.month,
                self.announced.day,
                tzinfo=UTC,
            ).timestamp()
        )


# /v1/huts/bookings and bookings.geojson have been OpenAPI-deprecated for a
# while (replacement: /huts/availability.geojson). The versioning rollout
# gives them a concrete sunset: 6 months after rollout (spec Q4 decision).
ENDPOINT_DEPRECATIONS: dict[str, EndpointDeprecation] = {
    "get_hut_bookings": EndpointDeprecation(
        announced=date(2026, 10, 1),
        sunset=date(2027, 4, 1),
        detail="Use /v1/huts/availability.geojson instead.",
    ),
    "get_hut_bookings_geojson": EndpointDeprecation(
        announced=date(2026, 10, 1),
        sunset=date(2027, 4, 1),
        detail="Use /v1/huts/availability.geojson instead.",
    ),
}


@dataclass(frozen=True)
class VersionChange:
    """A breaking change that introduced a new contract version.

    ``responses``/``requests`` map the Ninja operation id (explicit
    ``operation_id`` or ninja's generated one) to a transform:

    - ``responses``: downgrade — newest→oldest applied after the handler
      produced the latest shape.
    - ``requests``: upgrade — oldest→newest applied before the handler
      consumes the request (machinery present; first real use deferred to
      the first breaking change that needs one).

    Transforms must be defensive: ``pop(key, None)``, only rename/convert
    when the key is present, tolerate ``null`` and fields dropped by
    ``include``/``exclude``/``embed_*``.
    """

    version: str  # YYYY-MM-DD, compared lexically
    description: str = ""
    responses: dict[str, Transform] = field(default_factory=dict)
    requests: dict[str, Transform] = field(default_factory=dict)
    deprecation_date: date | None = None
    sunset_date: date | None = None


# The registry. Order is not significant (versions are sorted), but keep it
# chronological for readability. Add a new VersionChange ONLY for breaking
# changes (see README "Introducing a breaking change").
REGISTRY: list[VersionChange] = [
    VersionChange(
        version=INITIAL_VERSION,
        description="Initial version: rollout of the versioning system.",
    ),
]


def versions() -> list[str]:
    """All registered version identifiers, oldest first."""
    return sorted(change.version for change in REGISTRY)


def current_version() -> str:
    """Newest registered version — what unpinned clients receive."""
    return versions()[-1]


def default_version() -> str:
    """Version served when a client pins nothing (staged-rollout hook)."""
    return current_version()


def get_change(version: str) -> VersionChange | None:
    for change in REGISTRY:
        if change.version == version:
            return change
    return None


def is_valid_version(version: str) -> bool:
    return version in versions()


def version_status(version: str, *, today: date | None = None) -> str:
    """Lifecycle status: current | default | deprecated | sunset."""
    today = today or datetime.now(tz=UTC).date()
    change = get_change(version)
    if change is None:
        msg = f"Unknown API version: {version}"
        raise ValueError(msg)
    if version == current_version():
        return "current"
    if change.sunset_date and today > change.sunset_date:
        return "sunset"
    if change.deprecation_date is not None:
        return "deprecated"
    return "default"


def is_sunset(version: str, *, today: date | None = None) -> bool:
    return version_status(version, today=today) == "sunset"


def deprecation_info(version: str) -> VersionChange | None:
    """The change entry if ``version`` is deprecated (not current)."""
    change = get_change(version)
    if change is None or version == current_version():
        return None
    return change if change.deprecation_date is not None else None


def changes_after(version: str) -> list[VersionChange]:
    """All changes newer than ``version``, newest first (downgrade order)."""
    return sorted(
        (change for change in REGISTRY if change.version > version),
        key=lambda change: change.version,
        reverse=True,
    )


def content_hash() -> str:
    """Stable hash over versions and registered transforms.

    Joins the ETag key material of versioned endpoints (design.md D11):
    registering a new transform changes the ETag even when the underlying
    data did not change.
    """
    payload = [
        {
            "version": change.version,
            "responses": sorted(change.responses),
            "requests": sorted(change.requests),
            "sunset": change.sunset_date.isoformat() if change.sunset_date else None,
        }
        for change in sorted(REGISTRY, key=lambda change: change.version)
    ]
    blob = json.dumps(payload, sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


def deprecation_unix(change: VersionChange) -> int | None:
    """Unix timestamp for the RFC 9745 ``Deprecation`` header."""
    if change.deprecation_date is None:
        return None
    return int(
        datetime(
            change.deprecation_date.year,
            change.deprecation_date.month,
            change.deprecation_date.day,
            tzinfo=UTC,
        ).timestamp()
    )

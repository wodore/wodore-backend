"""/v1 root utilities: version info and sitemaps.

The sitemap endpoints are plain Django views (non-JSON): they are wired
via ``external_path`` with ``openapi=None`` — hidden from the OpenAPI
schema, exactly like the former ``include_in_schema=False``.
"""

import datetime
from os import environ
from typing import Any

import pydantic
from dmr import modify
from dmr.routing import external_path, path
from pydantic import Field

from django.http import HttpRequest, HttpResponse

from server.apps.api.controller import ApiController
from server.apps.api.sitemap import (
    SITEMAP_INDEX_TTL,
    SITEMAP_TTL,
    sitemap_huts,
    sitemap_index,
    sitemap_places,
    sitemap_static,
)
from server.settings.components.common import (
    BUILD_TIMESTAMP,
    get_git_long_hash,
    get_git_short_hash,
)


def _get_package_version() -> str:
    """Get package version from pyproject.toml or package metadata."""
    try:
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore

        from pathlib import Path

        pyproject_path = Path(__file__).parents[3] / "pyproject.toml"
        if pyproject_path.exists():
            with open(pyproject_path, "rb") as f:
                data = tomllib.load(f)
                version = data.get("project", {}).get("version")
                if version:
                    return version
    except Exception:
        pass

    try:
        from importlib.metadata import version as get_version

        return get_version("wodore-backend")
    except Exception:
        pass

    return "unknown"


PACKAGE_VERSION = _get_package_version()
DJANGO_ENV = environ.get("DJANGO_ENV", "development")


def _build_timestamp() -> datetime.datetime:
    """Parse BUILD_TIMESTAMP into a datetime, tolerating garbage.

    The alpine production image (the CI default distro) baked an
    unparseable BusyBox date(1) artifact into BUILD_TIMESTAMP (its
    date does not support ``%N``; the Dockerfiles used
    ``date +%6NZ``), and ``fromisoformat`` raised ValueError —
    turning ``GET /v1/version`` into a 500 on staging. Build
    metadata is best-effort: the version discovery endpoint must
    stay reachable, so an invalid value falls back to import time
    (same semantics as an unset BUILD_TIMESTAMP in dev).
    """
    try:
        return datetime.datetime.fromisoformat(BUILD_TIMESTAMP)
    except ValueError:
        return datetime.datetime.now()


class ApiVersionEntry(pydantic.BaseModel):
    """One registered API version with lifecycle status."""

    version: str = Field(
        description="API contract version (YYYY-MM-DD)",
        json_schema_extra={"example": "2026-10-01"},
    )
    status: str = Field(
        description=("Lifecycle: current, default, deprecated or sunset"),
        json_schema_extra={"example": "deprecated"},
    )
    sunset: str | None = Field(
        None,
        description=(
            "Sunset date (YYYY-MM-DD) of deprecated versions; after "
            "this date the version answers 410."
        ),
        json_schema_extra={"example": "2027-04-01"},
    )


class ApiVersionsBlock(pydantic.BaseModel):
    """Supported API contract versions."""

    current: str = Field(description="Newest registered API version")
    default: str = Field(description="Version served when a client pins nothing")
    supported: list[ApiVersionEntry] = Field(
        description="All registered API versions with lifecycle status"
    )


class VersionSchema(pydantic.BaseModel):
    """Build and runtime version information."""

    hash: str = Field(description="Git commit short hash")
    hash_long: str = Field(description="Git commit full hash")
    version: str = Field(description="Semantic version")
    timestamp: datetime.datetime = Field(description="Build timestamp")
    environment: str = Field(
        description="Current environment (development, production)"
    )
    api: ApiVersionsBlock = Field(
        description="API contract versions (see the Api-Version header)"
    )


class VersionController(ApiController):
    """Build/runtime/API version information."""

    @modify(operation_id="get_version", tags=["version"])
    def get(self) -> VersionSchema:
        """Get version information.

        Includes git short hash, full hash, package version, build
        timestamp, environment, and supported API versions.
        """
        from server.apps.apiversions import registry

        supported = [
            {
                "version": version,
                "status": registry.version_status(version),
                "sunset": (
                    change.sunset_date.isoformat()
                    if (change := registry.get_change(version)) and change.sunset_date
                    else None
                ),
            }
            for version in registry.versions()
        ]
        return VersionSchema(
            hash=get_git_short_hash(),
            hash_long=get_git_long_hash(),
            version=PACKAGE_VERSION,
            timestamp=_build_timestamp(),
            environment=DJANGO_ENV,
            api={
                "current": registry.current_version(),
                "default": registry.default_version(),
                "supported": supported,
            },
        )


def _xml_response(document: str, ttl: int = SITEMAP_TTL) -> HttpResponse:
    response = HttpResponse(document, content_type="application/xml; charset=utf-8")
    response["Cache-Control"] = f"public, max-age={ttl}"
    return response


def get_sitemap_index(request: HttpRequest) -> HttpResponse:
    """Sitemap index for wodore.com (static pages + paginated hut sitemaps).

    The frontend nginx proxies ``wodore.com/sitemap.xml`` here; all listed
    URLs (and the child sitemaps) are absolute wodore.com URLs.
    """
    return _xml_response(sitemap_index(), SITEMAP_INDEX_TTL)


def get_sitemap_static(request: HttpRequest) -> HttpResponse:
    """Canonical frontend entry pages of wodore.com."""
    return _xml_response(sitemap_static(), SITEMAP_INDEX_TTL)


def _json_error(status: int, code: str, detail: str) -> HttpResponse:
    """Plain-Django JSON error (external views are outside dmr handlers)."""
    import json

    return HttpResponse(
        json.dumps({"code": code, "detail": detail}),
        content_type="application/json",
        status=status,
    )


def get_sitemap_places(request: HttpRequest, page: int) -> HttpResponse:
    """One page of place URLs (name+description places only, opt-in gate)."""
    if page < 0:
        return _json_error(404, "not_found", "Sitemap page numbers start at 0.")
    document = sitemap_places(page)
    if document is None:
        return _json_error(404, "not_found", f"No places for sitemap page {page}.")
    return _xml_response(document)


def get_sitemap_huts(request: HttpRequest, page: int) -> HttpResponse:
    """One page of public hut URLs (SITEMAP_PAGE_SIZE per file)."""
    if page < 0:
        return _json_error(404, "not_found", "Sitemap page numbers start at 0.")
    document = sitemap_huts(page)
    if document is None:
        return _json_error(404, "not_found", f"No huts for sitemap page {page}.")
    return _xml_response(document)


paths: list[Any] = [
    path("version", VersionController.as_view(), name="get_version"),
    # Sitemaps: hidden from the schema (former include_in_schema=False)
    external_path(
        "sitemap.xml", get_sitemap_index, openapi=None, name="get_sitemap_index"
    ),
    external_path(
        "sitemap-static.xml",
        get_sitemap_static,
        openapi=None,
        name="get_sitemap_static",
    ),
    external_path(
        "sitemap-huts-<int:page>.xml",
        get_sitemap_huts,
        openapi=None,
        name="get_sitemap_huts",
    ),
    external_path(
        "sitemap-places-<int:page>.xml",
        get_sitemap_places,
        openapi=None,
        name="get_sitemap_places",
    ),
]

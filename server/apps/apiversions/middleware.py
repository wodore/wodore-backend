"""API version middleware: resolution, lifecycle headers, transforms.

One middleware does everything the former trio
(``ApiVersionMiddleware`` + ninja ``wrap_api`` + ``VersionedRenderer``)
did — without touching any framework internals:

* Resolution (``Api-Version`` header → ``api_version`` query → latest)
  and the ``Deprecation``/``Sunset``/``Link``/``Vary`` headers.
* Endpoint-identity: dmr endpoints are real Django views with URL
  names, so ``request.resolver_match.url_name`` *is* the operation id
  after routing — no operation wrapping needed (the old ``wrap.py``
  monkey-patched ``operation.run`` on ninja's bound routers for this).
* Response downgrades for pinned older versions: JSON responses are
  transformed in place (decode → transform → encode). Direct-write
  GeoJSON endpoints no longer need to call a transform helper — the
  middleware covers every endpoint uniformly.

Endpoint *sunset enforcement* (410 past the sunset date) moved from
``wrap_api`` into the affected handlers via
:func:`server.apps.apiversions.registry.guard_endpoint_sunset` — two
bookings endpoints, explicit instead of invisible wrapping.

Scope (design.md D3): everything under ``/v1/`` except:

- ``/v1/version`` — must stay reachable so clients can discover versions;
- paths ending in ``.svg`` — SVG redirects are identical for all versions
  and never raise version errors;
- ``/v1/docs`` and ``/v1/openapi.json`` — validate ``api_version`` (it
  selects the snapshot/schema) but carry no versioning response headers.

Place AFTER ``corsheaders.middleware.CorsMiddleware`` so error responses
keep their CORS headers.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import msgspec
import structlog

from django.http import HttpRequest, HttpResponse
from django.utils.cache import patch_vary_headers

from . import registry
from .transforms import downgrade_response

logger = structlog.get_logger("apiversions")

VERSION_HEADER = "Api-Version"
VERSION_QUERY_PARAM = "api_version"
EXCLUDED_EXACT_PATHS = frozenset({"/v1/version"})
# Docs/schema paths: validate ``api_version`` (it selects the snapshot)
# but carry no versioning response headers (design.md D3).
SCHEMA_PATHS = frozenset({"/v1/docs", "/v1/openapi.json"})


def _error_response(status: int, code: str, detail: str) -> HttpResponse:
    return HttpResponse(
        json.dumps({"code": code, "detail": detail}),
        content_type="application/json",
        status=status,
    )


def resolve_version(
    request: HttpRequest,
) -> tuple[str | None, str | None, HttpResponse | None]:
    """Resolve the requested version.

    Returns ``(version, source, error_response)`` — exactly one of
    ``version``/``error_response`` is set. ``source`` is ``header``,
    ``query`` or ``default``.
    """
    header = request.headers.get(VERSION_HEADER)
    query = request.GET.get(VERSION_QUERY_PARAM)

    if header is not None and query is not None and header != query:
        return (
            None,
            None,
            _error_response(
                400,
                "validation_error",
                f"'{VERSION_HEADER}' header ({header!r}) and "
                f"'{VERSION_QUERY_PARAM}' query parameter ({query!r}) differ.",
            ),
        )

    raw = header if header is not None else query
    if raw is None:
        return registry.default_version(), "default", None

    version = raw.strip()
    if not registry.is_valid_version(version):
        supported = ", ".join(registry.versions())
        return (
            None,
            None,
            _error_response(
                400,
                "validation_error",
                f"Unknown API version {version!r}. Supported: {supported}.",
            ),
        )
    source = "header" if header is not None else "query"
    return version, source, None


class ApiVersionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        path = request.path
        if (
            not path.startswith("/v1/")
            or path in EXCLUDED_EXACT_PATHS
            or path.endswith(".svg")
        ):
            return self.get_response(request)

        version, source, error = resolve_version(request)
        if error is not None:
            return error

        # Sunset versions are rejected everywhere except the discovery
        # endpoint (excluded above) — docs/schema included: a sunset
        # version's snapshot is of no use anymore.
        if registry.is_sunset(version):
            change = registry.get_change(version)
            sunset = change.sunset_date if change else None
            return _error_response(
                410,
                "api_version_sunset",
                f"API version {version!r} was sunset on "
                f"{sunset.isoformat() if sunset else 'unknown'}. "
                "Upgrade the pinned API version (see /v1/version).",
            )

        if source == "default":
            logger.info("api_version_unpinned", path=path, default_version=version)

        request.api_version = version
        request.api_version_source = source

        response = self.get_response(request)

        if path in SCHEMA_PATHS:
            return response

        self._downgrade_response(request, response)
        self._add_version_headers(request, response)
        return response

    def _downgrade_response(self, request: HttpRequest, response: HttpResponse) -> None:
        """Transform JSON bodies down to the pinned older version."""
        version = getattr(request, "api_version", None)
        if version is None or version == registry.current_version():
            return
        if response.status_code >= 400:
            return  # error bodies keep the latest shape (unversioned)
        if response.status_code in (204, 304) or not response.content:
            return  # bodyless responses carry nothing to transform
        content_type = response.headers.get("Content-Type", "")
        if not content_type.startswith("application/json"):
            return
        match = getattr(request, "resolver_match", None)
        op_id = getattr(match, "url_name", None) if match else None
        if not op_id:
            return
        data = msgspec.json.decode(response.content)
        data = downgrade_response(version, op_id, data)
        response.content = msgspec.json.encode(data)
        # The re-encoded body has a new length. Any Content-Length stamped
        # earlier is now wrong: CommonMiddleware (inner) sets it on the
        # pre-downgrade body for non-streaming responses, and uvicorn
        # hard-fails a response whose body doesn't match the header
        # ("Response content shorter than Content-Length") — the error
        # that truncated responses and leaked DB pool connections in the
        # 2026-10-05 staging wedge. Keep the header, but make it truthful.
        response.headers["Content-Length"] = str(len(response.content))

    def _add_version_headers(
        self, request: HttpRequest, response: HttpResponse
    ) -> None:
        version = getattr(request, "api_version", None)
        if version is None:
            return
        response[VERSION_HEADER] = version
        # Vary for header-resolved AND unpinned (default) responses: a
        # stored unpinned response (current-version body) must never be
        # reused for a later pinned request on the same URL (RFC 9111
        # allows exactly that without Vary). Query-resolved responses differ
        # by URL and stay Vary-free per design.md D11.
        if getattr(request, "api_version_source", None) in {"header", "default"}:
            # merge (corsheaders already varies on Origin)
            patch_vary_headers(response, (VERSION_HEADER,))

        # Version-level deprecation (the *version* the client pinned).
        change = registry.deprecation_info(version)
        if change is not None and change.sunset_date is not None:
            unix = registry.deprecation_unix(change)
            response["Deprecation"] = f"@{unix}"
            response["Sunset"] = change.sunset_date.strftime(
                "%a, %d %b %Y 00:00:00 GMT"
            )
            response["Link"] = f'<{registry.CHANGELOG_URL}>; rel="deprecation"'

        # Endpoint-level deprecation (e.g. deprecated bookings endpoints),
        # only for headers not already set by the version-level block.
        # Endpoint identity = URL name (dmr paths are named by operation id).
        match = getattr(request, "resolver_match", None)
        op_id = getattr(match, "url_name", None) if match else None
        if op_id is not None:
            dep = registry.ENDPOINT_DEPRECATIONS.get(op_id)
            if dep is not None and datetime.now(tz=UTC).date() <= dep.sunset:
                response.setdefault("Deprecation", f"@{dep.announced_unix}")
                response.setdefault(
                    "Sunset",
                    dep.sunset.strftime("%a, %d %b %Y 00:00:00 GMT"),
                )
                response.setdefault("Link", f'<{dep.link}>; rel="deprecation"')

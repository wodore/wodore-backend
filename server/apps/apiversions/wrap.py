"""Wrap Ninja operations: stash operation context and guard endpoint sunsets.

``wrap_api(api)`` walks the bound routers after all ``add_router`` calls and
wraps each ``operation.run`` — the exact wrapping pattern ninja's own router
decorators use (``ninja/router.py::_apply_decorators_to_operations``). The
wrapper stashes ``request.ninja_operation`` (used by the renderer and the
middleware for endpoint-level deprecation headers) and answers ``410`` for
endpoint-deprecated operations past their sunset date.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from functools import wraps
from typing import Any

from django.http import HttpRequest, HttpResponse
from django.utils.http import http_date

from . import registry
from .transforms import effective_operation_id

# Operations excluded from versioning: they never get ``ninja_operation``
# stashed (renderer stays a no-op) and the middleware skips them by path
# (design.md D3): SVG redirects (path suffix), ``/v1/version``, the OpenAPI
# schema and the docs views.
EXCLUDED_OPERATION_IDS = frozenset(
    {
        "get_version",
        "get_symbol_svg",
        "get_category_symbol_svg",
        "get_category_symbol_svg_with_parent",
        "get_weather_code_svg",
    }
)


def _sunset_response(dep: registry.EndpointDeprecation) -> HttpResponse:
    sunset_ts = int(
        datetime(
            dep.sunset.year, dep.sunset.month, dep.sunset.day, tzinfo=UTC
        ).timestamp()
    )
    body = json.dumps({"code": "endpoint_sunset", "detail": dep.detail})
    response = HttpResponse(body, content_type="application/json", status=410)
    response["Deprecation"] = f"@{dep.announced_unix}"
    response["Sunset"] = http_date(sunset_ts)
    response["Link"] = f'<{dep.link}>; rel="deprecation"'
    return response


def wrap_api(api: Any) -> int:
    """Wrap all mounted operations. Call once, after the last add_router.

    Returns the number of wrapped operations. Walks the *bound* routers
    (``api._get_bound_routers()``) — URL generation dispatches through the
    BoundRouters' cloned operations, not the registered router templates,
    so wrapping templates would silently miss every request.
    """
    wrapped = 0
    for bound in api._get_bound_routers():
        for path_view in bound.path_operations.values():
            for operation in path_view.operations:
                op_id = effective_operation_id(operation, api)
                if op_id in EXCLUDED_OPERATION_IDS:
                    continue
                operation.run = _wrap_operation(operation, op_id)
                wrapped += 1
    return wrapped


def _wrap_operation(operation: Any, op_id: str) -> Any:
    original_run = operation.run

    @wraps(original_run)
    def run(request: HttpRequest, **kwargs: Any) -> Any:
        request.ninja_operation = operation
        # Looked up per request (not captured) so tests and future dynamic
        # deprecations can adjust the registry.
        dep = registry.ENDPOINT_DEPRECATIONS.get(op_id)
        if dep is not None and datetime.now(tz=UTC).date() > dep.sunset:
            return _sunset_response(dep)
        return original_run(request, **kwargs)

    return run

"""Versioned renderer: response downgrades for regular Ninja operations.

``NinjaAPI.create_response`` has no operation context (verified against
django-ninja 1.6), so the renderer is the interception point: it receives
the serialized Python data plus the request, and the operation is stashed
on the request by :mod:`server.apps.apiversions.wrap`. Direct-write
endpoints bypass the renderer entirely and call
:func:`server.apps.apiversions.transforms.apply_response_transforms`
explicitly.
"""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest

from server.apps.api.renderer import MsgSpecRenderer

from .transforms import downgrade_response, effective_operation_id


class VersionedRenderer(MsgSpecRenderer):
    """MsgSpecRenderer that downgrades responses to the requested version."""

    def render(self, request: HttpRequest, data: Any, *, response_status: int) -> Any:
        version = getattr(request, "api_version", None)
        operation = getattr(request, "ninja_operation", None)
        if version is not None and operation is not None and response_status < 400:
            # Error bodies (ninja routes them through create_response too)
            # keep the latest shape: error contracts are not versioned.
            data = downgrade_response(version, effective_operation_id(operation), data)
        return super().render(request, data, response_status=response_status)

"""Startup validation: registry references must resolve against the API.

Every operation id referenced by a ``VersionChange`` transform or an
endpoint deprecation must exist in the live OpenAPI schema. This catches
typos and — the more likely case — silent breakage when a handler function
rename changes an auto-generated operation id (only ~37 of ~54 operations
carry an explicit ``operation_id`` today).
"""

from __future__ import annotations

from typing import Any

from django.core import checks

from . import registry

E001 = "apiversions.E001"
E002 = "apiversions.E002"


def _collect_schema_operation_ids() -> set[str]:
    from server.apps.api.api_v1 import get_openapi_schema

    schema = get_openapi_schema()
    ids: set[str] = set()
    for methods in schema.get("paths", {}).values():
        for operation in methods.values():
            if isinstance(operation, dict) and "operationId" in operation:
                ids.add(operation["operationId"])
    return ids


def _referenced_operation_ids() -> dict[str, str]:
    """Map referenced operation id → what references it (for error text)."""
    references: dict[str, str] = {}
    for change in registry.REGISTRY:
        for op_id in {*change.responses, *change.requests}:
            references[op_id] = f"VersionChange {change.version}"
    for op_id in registry.ENDPOINT_DEPRECATIONS:
        references[op_id] = "endpoint deprecation"
    return references


@checks.register(checks.Tags.compatibility)
def check_registry_operation_ids(
    app_configs: Any = None, **kwargs: Any
) -> list[checks.CheckMessage]:
    errors: list[checks.CheckMessage] = []
    references = _referenced_operation_ids()
    if not references:
        return errors

    try:
        schema_ids = _collect_schema_operation_ids()
    except Exception as exc:  # pragma: no cover - defensive
        return [
            checks.Warning(
                f"Could not build the OpenAPI schema to validate the API "
                f"version registry: {exc}",
                id=E002,
            )
        ]

    for op_id, source in sorted(references.items()):
        if op_id not in schema_ids:
            errors.append(
                checks.Error(
                    f"{source} references operation id {op_id!r}, which "
                    f"does not exist in the live OpenAPI schema. Typo, or "
                    f"was a handler (re)named? Endpoints with transforms "
                    f"must have a stable, explicit operation_id.",
                    id=E001,
                )
            )
    return errors

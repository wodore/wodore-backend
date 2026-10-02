"""Startup validation: registry references must resolve against the API.

Every operation id referenced by a ``VersionChange`` transform or an
endpoint deprecation must exist in the live OpenAPI schema. This catches
typos and — the more likely case — silent breakage when a handler function
rename changes an auto-generated operation id (only ~37 of ~54 operations
carry an explicit ``operation_id`` today).

The second invariant (E003/E004): URL name == operationId. The API-version
middleware identifies endpoints at runtime by the Django URL name
(``request.resolver_match.url_name``) while the registry, the CI check
above and every OpenAPI consumer key on ``operationId``. Both are set to
the same string on every dmr route by convention — this check makes that
convention structural: a name/operationId mismatch fails at startup
(and in CI) instead of silently disabling versioning for that endpoint.
"""

from __future__ import annotations

from typing import Any

from django.core import checks
from django.urls import URLPattern, URLResolver, get_resolver

from . import registry

E001 = "apiversions.E001"
E002 = "apiversions.E002"
E003 = "apiversions.E003"
E004 = "apiversions.E004"

# URL names that are intentionally NOT in the OpenAPI schema: plain
# Django views wired via ``external_path(openapi=None)`` (hidden like the
# former ninja ``include_in_schema=False``). Everything else under /v1
# with a URL name must carry a matching operationId.
HIDDEN_URL_NAMES = frozenset(
    {
        "get_sitemap_index",
        "get_sitemap_static",
        "get_sitemap_huts",
        "get_hut_markdown",
    }
)


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


def _collect_v1_url_names() -> set[str]:
    """Named URL patterns under /v1/ (namespace names excluded)."""

    def walk(patterns: Any, prefix: str = "") -> set[str]:
        names: set[str] = set()
        for pattern in patterns:
            route = getattr(pattern, "pattern", None)
            if isinstance(pattern, URLPattern):
                if prefix.startswith("v1") and pattern.name:
                    names.add(pattern.name)
            elif isinstance(pattern, URLResolver):
                names |= walk(pattern.url_patterns, prefix + str(route))
        return names

    return walk(get_resolver().url_patterns)


@checks.register(checks.Tags.compatibility)
def check_url_names_match_operation_ids(
    app_configs: Any = None, **kwargs: Any
) -> list[checks.CheckMessage]:
    """URL name == operationId for every versioned endpoint (design D2)."""
    try:
        schema_ids = _collect_schema_operation_ids()
    except Exception as exc:  # pragma: no cover - defensive
        return [
            checks.Warning(
                f"Could not build the OpenAPI schema to validate URL names: {exc}",
                id=E002,
            )
        ]

    url_names = _collect_v1_url_names()
    named_endpoints = url_names - HIDDEN_URL_NAMES

    errors: list[checks.CheckMessage] = []
    for name in sorted(named_endpoints - schema_ids):
        errors.append(
            checks.Error(
                f"URL name {name!r} has no matching operationId in the "
                f"OpenAPI schema. The API-version middleware identifies "
                f"endpoints by URL name, the registry/CI/consumers by "
                f"operationId — both must be the same string: set "
                f"@modify(operation_id={name!r}) (or add the route to "
                f"HIDDEN_URL_NAMES when it is deliberately undocumented).",
                hint="name == operation_id is a load-bearing invariant of "
                "the versioning system (apiversions design D2).",
                id=E003,
            )
        )
    for op_id in sorted(schema_ids - url_names):
        errors.append(
            checks.Error(
                f"operationId {op_id!r} has no matching URL name under /v1/. "
                f"The middleware cannot identify this endpoint at runtime "
                f"(resolver_match.url_name), so version transforms and "
                f"endpoint deprecations keyed on it will never fire. Give "
                f"the route name={op_id!r}.",
                hint="name == operation_id is a load-bearing invariant of "
                "the versioning system (apiversions design D2).",
                id=E004,
            )
        )
    return errors

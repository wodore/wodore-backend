"""Property-based contract testing against a LIVE Wodore API (schemathesis).

schemathesis fuzzes requests derived from the OpenAPI schema and fails
on any response violating the documented contract (status codes,
response shapes). The snapshot system pins the DOCUMENT - this checks
the BEHAVIOUR.

Runs against a running server (dev server, docker-compose, staging or
production) so the full middleware/DB stack behaves exactly like real
traffic:

    WODORE_CONTRACT_BASE_URL=http://localhost:3430 \
        scripts/lane-run.sh .venv/bin/pytest tests/contract -m api_contract

Without the variable the test skips (green in the normal suite; wire
the variable in CI against a bootet server to make it mandatory).

Bounded to read-only operations without external side effects (the
image providers hit the network; feedback writes, mails and is
throttled) - those keep their targeted tests.
"""

from __future__ import annotations

import os

import pytest

pytestmark = [pytest.mark.api_contract]

BASE_URL = os.environ.get("WODORE_CONTRACT_BASE_URL")

SAFE_OPERATIONS = frozenset(
    {
        "get_version",
        "get_organizations",
        "get_organization",
        "get_symbols",
        "get_symbol_by_id",
        "get_symbols_by_slug",
        "get_symbol_by_style_and_slug",
        "get_weather_codes",
        "get_weather_code",
        "get_category_tree",
        "get_category_list_all",
        "get_category_map_all",
    }
)


@pytest.mark.skipif(
    not BASE_URL,
    reason="set WODORE_CONTRACT_BASE_URL to a running API to execute",
)
def test_contract_holds_for_safe_operations():
    """Every SAFE operation accepts schema-derived requests and answers
    within the documented contract (10 fuzz cases per operation)."""
    import django

    django.setup()

    import schemathesis

    schema = schemathesis.openapi.from_url(f"{BASE_URL}/v1/openapi.json")

    operations = []
    for result in schema.get_all_operations():
        op = result.ok()
        if op.definition.raw.get("operationId") in SAFE_OPERATIONS:
            operations.append(op)
    assert operations, "no SAFE operations found in the schema"

    failures = []
    for operation in operations:
        from hypothesis import HealthCheck, given, settings

        strategy = schema.get_case_strategy(operation=operation)

        @given(case=strategy)
        @settings(
            max_examples=10,
            deadline=None,
            suppress_health_check=list(HealthCheck),
        )
        def run_cases(case):
            case.call_and_validate()

        try:
            run_cases()
        except Exception as exc:  # collect, report at end
            failures.append(
                (operation.definition.raw.get("operationId"), str(exc)[:400])
            )

    assert not failures, f"contract violations: {failures}"

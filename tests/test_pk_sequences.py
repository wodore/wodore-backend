"""Regression guard for the order-dependent pk-sequence flake.

CI run 37381918302 (PR #270): with ``pytest-randomly`` shuffling, unseeded
tests ran before ``seed_data`` and factory inserts collided with
fixture-loaded explicit-pk rows on the reused CI database (UniqueViolation
on ``organizations_organization_pkey``). The reset now applies to every
test via an autouse fixture; this module pins the invariant it establishes.

The test below is deliberately unseeded (plain ``django_db`` mark, no
``seed_data``): it passes only when the sequence reset applies to tests
that never request the seeding fixture.
"""

import pytest

from django.apps import apps
from django.db import connection


@pytest.mark.django_db
def test_pk_sequences_sit_above_explicit_pks():
    """After setup, every pk sequence hands out ids above max(explicit pk)."""
    qn = connection.ops.quote_name
    with connection.cursor() as cursor:
        for model in apps.get_models():
            field = model._meta.auto_field
            if field is None:
                continue
            cursor.execute(
                "SELECT pg_get_serial_sequence(%s, %s)",
                [model._meta.db_table, field.column],
            )
            seq = cursor.fetchone()[0]
            if not seq:
                continue
            cursor.execute(f"SELECT last_value, is_called FROM {seq}")
            last_value, is_called = cursor.fetchone()
            cursor.execute(
                f"SELECT COALESCE(MAX({qn(field.column)}), 0) FROM {qn(model._meta.db_table)}"
            )
            max_pk = cursor.fetchone()[0]
            next_id = last_value + 1 if is_called else last_value
            assert next_id > max_pk, (
                f"{model.__name__}: sequence {seq} would hand out id {next_id}, "
                f"colliding with existing pk {max_pk}"
            )

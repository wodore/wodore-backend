"""Tests for per-hut error isolation in the hut import loop.

One hut with broken data (e.g. a stored ``HutSource.source_data`` payload
that fails pydantic re-validation in ``BaseService.convert()``, Sentry
BACKEND-DJANGO-Q) must fail alone — the import loop continues with the
remaining huts instead of aborting the whole run.
"""

from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from django.contrib.gis.geos import Point
from django.db import IntegrityError

from server.apps.huts.management.commands.huts import init_huts_db
from server.apps.huts.models import HutSource
from server.apps.organizations.models import Organization
from server.core import UpdateCreateStatus


def _hut_source(source_id: str, name: str) -> HutSource:
    """Unsaved HutSource with a location (enters the conversion path)."""
    return HutSource(
        source_id=source_id,
        organization=Organization(slug="prenota-rifugi"),
        name=name,
        location=Point(9.0, 45.0),
    )


def _fake_update_or_create(
    fail_source_ids: frozenset[str], error: BaseException
) -> Any:
    """Replacement for ``Hut.update_or_create`` failing for chosen sources."""
    calls: list[str] = []

    def update_or_create(**kwargs: Any) -> tuple[Any, UpdateCreateStatus]:
        hut_source: HutSource = kwargs["hut_source"]
        calls.append(hut_source.source_id)
        if hut_source.source_id in fail_source_ids:
            raise error
        return SimpleNamespace(slug=f"hut-{hut_source.source_id}"), (
            UpdateCreateStatus.created
        )

    return update_or_create, calls


def test_validation_error_fails_only_that_hut(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pydantic ValidationError isolates to one hut; the run continues."""
    poisoned = _hut_source("6674", "Agliata 138 Hospitality")
    healthy = [_hut_source("1", "Healthy One"), _hut_source("2", "Healthy Two")]
    error = ValidationError.from_exception_data(
        "PrenotaHutSource",
        [
            {
                "type": "string_type",
                "loc": ("source_data", "card", "img"),
                "input": None,
            }
        ],
    )
    fake, calls = _fake_update_or_create(frozenset({"6674"}), error)
    monkeypatch.setattr(
        "server.apps.huts.management.commands.huts.Hut.update_or_create", fake
    )

    added, _updated, _nochange, failed = init_huts_db([poisoned, *healthy])

    assert failed == 1
    assert added == 2
    assert calls == ["6674", "1", "2"]  # the loop ran past the failure


@pytest.mark.parametrize(
    ("error", "label"),
    [
        (IntegrityError("duplicate key value violates unique constraint"), "integrity"),
        (
            NotImplementedError("No service for organization 'x' found."),
            "not-implemented",
        ),
    ],
)
def test_known_db_errors_still_isolated(
    monkeypatch: pytest.MonkeyPatch, error: BaseException, label: str
) -> None:
    """The merged IntegrityError/NotImplementedError clause keeps isolating."""
    failing = _hut_source("1", f"Broken {label}")
    healthy = [_hut_source("2", "Healthy One"), _hut_source("3", "Healthy Two")]
    fake, calls = _fake_update_or_create(frozenset({"1"}), error)
    monkeypatch.setattr(
        "server.apps.huts.management.commands.huts.Hut.update_or_create", fake
    )

    added, _updated, _nochange, failed = init_huts_db([failing, *healthy])

    assert failed == 1
    assert added == 2
    assert calls == ["1", "2", "3"]


def test_unexpected_error_still_aborts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Genuinely unexpected errors stay loud — only known classes isolate."""
    failing = _hut_source("1", "Broken")
    fake, _calls = _fake_update_or_create(frozenset({"1"}), RuntimeError("boom"))
    monkeypatch.setattr(
        "server.apps.huts.management.commands.huts.Hut.update_or_create", fake
    )

    with pytest.raises(RuntimeError, match="boom"):
        init_huts_db([failing, _hut_source("2", "Never reached")])

"""Tests for the PhotosMode threading through the hut import.

`app huts` defaults to `PhotosMode.EMBEDDED` (only photos already part of the
stored `HutSource.source_data` - no extra provider requests). `--photos
none|all` overrides; the `--add-all` sequence pins `photos=all` for the
sources whose photos only exist behind extra requests (wikidata, refuges).
"""

from types import SimpleNamespace
from typing import Any

import pytest
from hut_services import PhotosMode

from django.contrib.gis.geos import Point

from server.apps.huts.management.commands.huts import init_huts_db
from server.apps.huts.models import Hut, HutSource
from server.apps.huts.models import _hut as _hut_module
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


def _fake_update_or_create() -> tuple[Any, list[dict[str, Any]]]:
    """Replacement for ``Hut.update_or_create`` capturing its kwargs."""
    calls: list[dict[str, Any]] = []

    def update_or_create(**kwargs: Any) -> tuple[Any, UpdateCreateStatus]:
        calls.append(kwargs)
        return SimpleNamespace(slug="hut-x"), UpdateCreateStatus.created

    return update_or_create, calls


def test_init_huts_db_defaults_to_embedded_photos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without --photos the import threads PhotosMode.EMBEDDED (no extra requests)."""
    fake, calls = _fake_update_or_create()
    monkeypatch.setattr(
        "server.apps.huts.management.commands.huts.Hut.update_or_create", fake
    )

    added, _updated, _nochange, failed = init_huts_db([_hut_source("1", "Hut One")])

    assert (added, failed) == (1, 0)
    assert calls[0]["include_photos"] is PhotosMode.EMBEDDED


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        (PhotosMode.NONE, PhotosMode.NONE),
        (PhotosMode.ALL, PhotosMode.ALL),
        (PhotosMode.EMBEDDED, PhotosMode.EMBEDDED),
    ],
)
def test_init_huts_db_threads_photos_mode(
    monkeypatch: pytest.MonkeyPatch, mode: PhotosMode, expected: PhotosMode
) -> None:
    """The selected mode reaches Hut.update_or_create unchanged."""
    fake, calls = _fake_update_or_create()
    monkeypatch.setattr(
        "server.apps.huts.management.commands.huts.Hut.update_or_create", fake
    )

    _added, _updated, _nochange, failed = init_huts_db(
        [_hut_source("1", "Hut One")], include_photos=mode
    )

    assert failed == 0
    assert calls[0]["include_photos"] is expected


def test_convert_source_forwards_photos_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hut._convert_source passes the mode to the organization's service."""
    seen: list[PhotosMode] = []

    class FakeService:
        def convert(
            self, _src: Any, include_photos: PhotosMode = PhotosMode.EMBEDDED
        ) -> str:
            seen.append(include_photos)
            return "converted"

    monkeypatch.setitem(_hut_module.SERVICES, "prenota-rifugi", FakeService())

    assert Hut._convert_source(_hut_source("1", "Hut One")) == "converted"
    Hut._convert_source(_hut_source("1", "Hut One"), include_photos=PhotosMode.NONE)

    assert seen == [PhotosMode.EMBEDDED, PhotosMode.NONE]

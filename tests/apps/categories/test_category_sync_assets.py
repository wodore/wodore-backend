"""category_sync_assets: stored SVGs are Martin-parseable.

The command is the production hop that turns ``assets/`` SVGs into
database Symbol files. The sanitizer must run here (staging 2026-11
incident: Martin 1.16 ``NoRootNode`` on ``ns0:``-prefixed elements and
roots without ``xmlns``) so the stored bytes — and everything
regenerated from them by ``martin_sync`` — never carry the lxml
artifacts forward.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from pytest_django.fixtures import SettingsWrapper

from django.core.files.base import ContentFile

from server.apps.categories.management.commands.category_sync_assets import Command
from server.apps.licenses.models import License
from server.apps.symbols.models import Symbol

DIRTY = (
    b'<svg xmlns:ns0="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
    b'<ns0:path d="M0 0h24v24H0z"/></svg>'
)


@pytest.fixture(autouse=True)
def _tmp_media(settings: SettingsWrapper, tmp_path: Path):
    """Keep symbol SVG files out of the repo checkout."""
    settings.MEDIA_ROOT = tmp_path / "media"


@pytest.fixture
def license_(db: None) -> License:
    _ = db  # pytest-django DB gate for this fixture
    return License.objects.create(slug="test-license", name="Test")


def _dirty_svg(tmp_path: Path) -> Path:
    path = tmp_path / "hut.svg"
    path.write_bytes(DIRTY)
    return path


def _command() -> Command:
    out, err = io.StringIO(), io.StringIO()
    return Command(stdout=out, stderr=err)


def _stored_bytes(slug: str, style: str = "color") -> bytes:
    symbol = Symbol.objects.get(slug=slug, style=style)
    return symbol.svg_file.read()


def test_created_symbol_stores_sanitized_svg(license_: License, tmp_path: Path) -> None:
    symbol, created = _command()._get_or_create_symbol(
        _dirty_svg(tmp_path), "color", "hut", license_, dry_run=False
    )

    assert symbol is not None and created
    stored = _stored_bytes("hut")
    assert b"ns0" not in stored
    assert stored.startswith(b'<svg xmlns="http://www.w3.org/2000/svg"')


def test_force_update_sanitizes_stored_svg(license_: License, tmp_path: Path) -> None:
    """Symbols already carrying dirty bytes (synced before the fix) are
    cleaned by the next ``--force`` run."""
    symbol = Symbol(slug="hut", style="color", search_text="hut", license=license_)
    symbol.svg_file.save("color__hut.svg", ContentFile(DIRTY), save=True)
    assert b"ns0" in _stored_bytes("hut")

    updated, created = _command()._get_or_create_symbol(
        _dirty_svg(tmp_path), "color", "hut", license_, dry_run=False, force=True
    )

    assert updated is not None and not created
    stored = _stored_bytes("hut")
    assert b"ns0" not in stored
    assert stored.startswith(b'<svg xmlns="http://www.w3.org/2000/svg"')

"""Tests for the symbol SVG redirect endpoint.

The 302 must stay declared in ``@modify`` (dmr response validation
rejects undeclared status codes) and carries the shared
``REDIRECT_CACHE_CONTROL`` policy.
"""

from __future__ import annotations

import pytest

from django.core.files.base import ContentFile
from django.test import Client

from server.apps.api.controller import REDIRECT_CACHE_CONTROL
from server.apps.licenses.models import License
from server.apps.symbols.models import Symbol

SVG_BODY = b'<svg xmlns="http://www.w3.org/2000/svg"/>'


def _make_symbol(slug: str, style: str) -> Symbol:
    """Create an active symbol with a stored SVG file."""
    license = License.objects.create(slug=f"license-{slug}")
    symbol = Symbol(slug=slug, style=style, license=license)
    symbol.svg_file.save(f"{slug}.svg", ContentFile(SVG_BODY), save=True)
    return symbol


@pytest.mark.django_db
class TestSymbolSvg:
    """GET /v1/symbols/{style}/{slug}.svg"""

    def test_redirects_to_svg(self):
        symbol = _make_symbol("test-mountain", Symbol.StyleChoices.color)

        response = Client().get("/v1/symbols/color/test-mountain.svg")

        assert response.status_code == 302
        assert response["Location"] == symbol.svg_file.url
        assert response["Cache-Control"] == REDIRECT_CACHE_CONTROL

    def test_unknown_slug_returns_404(self):
        response = Client().get("/v1/symbols/color/test-nope.svg")

        assert response.status_code == 404

    def test_wrong_style_returns_404(self):
        _make_symbol("test-mountain", Symbol.StyleChoices.color)

        response = Client().get("/v1/symbols/mono/test-mountain.svg")

        assert response.status_code == 404


# ── Content-hashed symbol storage ─────────────────────────────────────


@pytest.mark.django_db
class TestContentHashedStorage:
    """Media is immutable-cached: a filename must map to one content
    version. The old deterministic names let icon-import re-write files
    in place, leaving browsers on stale bytes (found live on staging)."""

    def test_save_derives_hashed_name_and_dedupes(self):
        from django.core.files.storage import default_storage

        symbol = _make_symbol("water", "color")
        # Name shape: symbols/water_<hash10>.svg
        stem = symbol.svg_file.name.rsplit("/", 1)[-1]
        assert stem.startswith("water_") and stem.endswith(".svg")
        assert len(stem.split("_")[-1].split(".")[0]) == 10

        # Same stem + same content -> deduped onto the existing file
        from server.apps.symbols.storage import hashed_name

        canonical = hashed_name("symbols/water.svg", ContentFile(SVG_BODY))
        assert canonical == symbol.svg_file.name
        assert default_storage.exists(canonical)

    def test_changed_content_gets_new_name_not_overwrite(self):
        symbol = _make_symbol("mountain", "color")
        first = symbol.svg_file.name
        symbol.svg_file.save("mountain.svg", ContentFile(b"<svg><changed/></svg>"))
        second = symbol.svg_file.name
        assert second != first
        assert second.rsplit("/", 1)[-1].startswith("mountain_")

    def test_hashed_name_strips_previous_suffix(self):
        from server.apps.symbols.storage import hashed_name

        content = ContentFile(b"<svg/>")
        once = hashed_name("symbols/water.svg", content)
        twice = hashed_name(once, content)
        assert once == twice  # canonical: re-saving stays stable

    def test_canonicalize_renames_legacy_files(self):
        from django.core.files.storage import default_storage

        from server.apps.symbols.storage import canonicalize_symbol_storage

        # Simulate a legacy deterministic-named file
        legacy_name = "symbols/legacy-icon_color.svg"
        default_storage.save(legacy_name, ContentFile(b"<svg><old/></svg>"))
        license = License.objects.create(slug="license-legacy")
        symbol = Symbol(slug="legacy-icon", style="color", license=license)
        symbol.svg_file = legacy_name
        symbol.save()

        stats = canonicalize_symbol_storage(Symbol)
        assert stats["renamed"] >= 1
        symbol.refresh_from_db()
        new_name = symbol.svg_file.name
        assert new_name != legacy_name
        assert default_storage.exists(new_name)
        assert not default_storage.exists(legacy_name)  # old file removed
        # Idempotent
        stats2 = canonicalize_symbol_storage(Symbol)
        assert stats2["renamed"] == 0
        assert stats2["skipped"] >= 1

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
        name = symbol.svg_file.name
        assert name is not None
        stem = name.rsplit("/", 1)[-1]
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
        assert second is not None
        assert first is not None
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
        new_name = symbol.svg_file.name  # type: ignore  # dynamic attr: plugin-less inference gap
        assert new_name is not None
        assert new_name != legacy_name
        assert default_storage.exists(new_name)
        assert not default_storage.exists(legacy_name)  # old file removed
        # Idempotent
        stats2 = canonicalize_symbol_storage(Symbol)
        assert stats2["renamed"] == 0
        assert stats2["skipped"] >= 1


@pytest.mark.django_db
class TestCoreStorageHelpers:
    """The shared server.core.storage helpers used by all media writers."""

    def test_save_content_hashed_helper(self):
        from django.core.files.storage import default_storage

        from server.core.storage import hashed_name, save_content_hashed

        name = save_content_hashed("og/maps/test-map.jpg", b"\xff\xd8fakejpeg")
        assert name == hashed_name(
            "og/maps/test-map.jpg", ContentFile(b"\xff\xd8fakejpeg")
        )
        assert default_storage.exists(name)
        # Idempotent for identical content
        again = save_content_hashed("og/maps/test-map.jpg", b"\xff\xd8fakejpeg")
        assert again == name

    def test_shared_hashed_media_storage_instance(self):
        from django.core.files.storage import default_storage

        from server.core.storage import hashed_media_storage, hashed_name

        # The shared instance used by Organization.logo, ContactFunction
        # .symbol and Image.image (field wiring via AlterField
        # migrations; model-level saves covered by the class tests).
        name = hashed_media_storage.save(
            "organizations/logos/logo.png", ContentFile(b"\x89PNG fake")
        )
        expected = hashed_name(
            "organizations/logos/logo.png", ContentFile(b"\x89PNG fake")
        )
        assert name == expected
        assert default_storage.exists(name)
        stem = name.rsplit("/", 1)[-1]
        assert stem.startswith("logo_") and stem.endswith(".png")


SVG_NO_XMLNS = (
    b'<svg viewBox="0 0 24 24" width="48" height="48">'
    b'<path fill="#5D4433" d="M0 0h1z"/></svg>'
)
SVG_NS0_PREFIX = (
    b'<svg xmlns:ns0="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
    b'<ns0:path fill="#5D4433" d="M0 0h1z"/></svg>'
)


@pytest.mark.django_db
class TestSanitizeSymbolStorage:
    """Migration 0017 — heal stored SVGs a browser cannot decode in <img>."""

    def test_rewrites_malformed_files(self):
        from django.core.files.storage import default_storage

        # Raw bytes on purpose: svg_file.save must not sanitize (the gap
        # this migration heals); clean files stay byte-identical.
        bad_no_ns = _make_symbol("test-selfhut", Symbol.StyleChoices.color)
        bad_no_ns.svg_file.save(
            "color__selfhut.svg", ContentFile(SVG_NO_XMLNS), save=True
        )
        old_no_ns = bad_no_ns.svg_file.name
        assert old_no_ns is not None
        bad_ns0 = _make_symbol("test-hut", Symbol.StyleChoices.color)
        bad_ns0.svg_file.save("color__hut.svg", ContentFile(SVG_NS0_PREFIX), save=True)
        old_ns0 = bad_ns0.svg_file.name
        assert old_ns0 is not None
        clean = _make_symbol("test-selfhut-mono", Symbol.StyleChoices.mono)
        clean_name = clean.svg_file.name

        from server.apps.symbols.storage import sanitize_symbol_storage

        stats = sanitize_symbol_storage(Symbol)

        assert stats["sanitized"] == 2
        assert stats["skipped"] >= 1
        for symbol, old_name in ((bad_no_ns, old_no_ns), (bad_ns0, old_ns0)):
            symbol.refresh_from_db()
            with symbol.svg_file.open("rb") as stored:
                body = stored.read()
            root = body[: body.index(b">") + 1]
            assert b'xmlns="http://www.w3.org/2000/svg"' in root
            assert b"xmlns:ns0" not in body
            assert symbol.svg_file.name != old_name  # new content hash
            assert not default_storage.exists(old_name)  # superseded file gone
        clean.refresh_from_db()
        assert clean.svg_file.name == clean_name  # untouched

    def test_dry_run_counts_without_writing(self):
        symbol = _make_symbol("test-bhotel", Symbol.StyleChoices.color)
        symbol.svg_file.save("color__bhotel.svg", ContentFile(SVG_NO_XMLNS), save=True)
        name_before = symbol.svg_file.name

        from server.apps.symbols.storage import sanitize_symbol_storage

        stats = sanitize_symbol_storage(Symbol, dry_run=True)

        assert stats["sanitized"] == 1
        symbol.refresh_from_db()
        assert symbol.svg_file.name == name_before

    def test_idempotent(self):
        from server.apps.symbols.storage import sanitize_symbol_storage
        from server.apps.symbols.svg import sanitize_svg

        symbol = _make_symbol("test-camping", Symbol.StyleChoices.color)
        symbol.svg_file.save(
            "color__camping.svg",
            ContentFile(sanitize_svg(SVG_NO_XMLNS)),
            save=True,
        )
        name = symbol.svg_file.name

        stats = sanitize_symbol_storage(Symbol)

        assert stats["sanitized"] == 0
        symbol.refresh_from_db()
        assert symbol.svg_file.name == name

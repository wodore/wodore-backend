"""Glyph templates: canonical Martin font route + the 0010 migration.

Regression coverage for the canonical Martin font route change (#363)
that the #444 test restructure dropped together with the old monolithic
``server/apps/basemaps/tests.py``:

* a fresh ``map_seed`` plants extension-less Martin glyph templates —
  Martin (≤ 1.16.1, the pinned prod/stage image) 301s ``.pbf``-suffixed
  font URLs to the canonical route while DROPPING the query string
  (``redirect_font_ext``), which would silently discard the serve-time
  ``?v=`` asset version and the watcher probe nonce;
* the ``0010`` data migration rewrites already-seeded ``.pbf`` templates
  in place — surgically (external font hosts survive byte-for-byte),
  idempotently, reversibly.
"""

from __future__ import annotations

import importlib

import pytest

from django.apps import apps as global_apps
from django.core.management import call_command

from server.apps.basemaps.models import MapLayer

MIGRATION = importlib.import_module(
    "server.apps.basemaps.migrations.0010_strip_pbf_from_martin_glyph_templates"
)

MARTIN_SUFFIX = "/font/{fontstack}/{range}"
PBF_SUFFIX = MARTIN_SUFFIX + ".pbf"


def _glyphs(layer: MapLayer) -> str:
    style = layer.style
    if isinstance(style, dict) and isinstance(style.get("glyphs"), str):
        return style["glyphs"]
    return ""


def _martin_layers() -> list[MapLayer]:
    return [
        layer
        for layer in MapLayer.objects.filter(style__isnull=False)
        if _glyphs(layer).endswith(MARTIN_SUFFIX)
    ]


def _martin_pks(layers: list[MapLayer]) -> list[int]:
    return [layer.pk for layer in layers]


@pytest.mark.django_db
class TestSeededGlyphTemplates:
    def test_fresh_seed_is_extensionless(self) -> None:
        call_command("map_seed", verbosity=0)
        layers = _martin_layers()
        assert layers, "seeded styles reference Martin glyphs"
        for layer in layers:
            glyphs = _glyphs(layer)
            assert glyphs.endswith(MARTIN_SUFFIX), glyphs
            assert ".pbf" not in glyphs, glyphs


@pytest.mark.django_db
class TestGlyphMigration:
    def test_strip_pbf_rewrites_stored_templates_surgically(self) -> None:
        call_command("map_seed", verbosity=0)

        # Rows as seeded BEFORE 0010: Martin templates carry the .pbf
        # suffix (any prefix — env token or root-relative).
        martin_layers = _martin_layers()
        assert martin_layers, "seeded styles reference Martin glyphs"
        for layer in martin_layers:
            style = layer.style
            assert isinstance(style, dict)
            glyphs = style.get("glyphs")
            assert isinstance(glyphs, str)
            style["glyphs"] = glyphs + ".pbf"
            layer.save(update_fields=["style"])

        # External font hosts (maptoolkit) also serve .pbf glyph URLs —
        # they must survive the migration byte-for-byte.
        external_before = {
            layer.pk: _glyphs(layer)
            for layer in MapLayer.objects.filter(style__isnull=False)
            if _glyphs(layer).endswith(".pbf") and MARTIN_SUFFIX not in _glyphs(layer)
        }
        assert external_before, "seed includes an external-font layer"

        MIGRATION.strip_pbf(global_apps, None)

        for pk in _martin_pks(martin_layers):
            glyphs = _glyphs(MapLayer.objects.get(pk=pk))
            assert glyphs.endswith(MARTIN_SUFFIX), glyphs
            assert ".pbf" not in glyphs, glyphs
        for pk, glyphs in external_before.items():
            assert _glyphs(MapLayer.objects.get(pk=pk)) == glyphs

        # Idempotent: a second pass finds nothing left to strip.
        MIGRATION.strip_pbf(global_apps, None)
        for pk in _martin_pks(martin_layers):
            assert _glyphs(MapLayer.objects.get(pk=pk)).endswith(MARTIN_SUFFIX)

        # Reverse restores the suffix on Martin templates only.
        MIGRATION.restore_pbf(global_apps, None)
        for pk in _martin_pks(martin_layers):
            assert _glyphs(MapLayer.objects.get(pk=pk)).endswith(PBF_SUFFIX)
        for pk, glyphs in external_before.items():
            assert _glyphs(MapLayer.objects.get(pk=pk)) == glyphs

"""MLT opt-in: explicit ``.mlt`` URL space + ``encoding: mlt`` marker.

Covers the ``map-style-api`` delta (the rendering pipeline preserves a
vector source's ``encoding`` verbatim in resolved and tokenized modes,
never injects one) and the seed pairing contract for the huts overlay
(``.mlt`` tiles template always ships with ``encoding: mlt``; every other
vector source stays MVT — phase 1 scopes the Martin-side conversion to
the huts table source only).

Tile-origin URLs use the ``{{env:MARTIN_TILE_URL}}`` registry token —
the pre-unification ``{TILE_SERVER_URL}`` placeholder is gone entirely
(basemaps migration 0011 rewrites stored rows).
"""

from __future__ import annotations

from typing import Any

import pytest

from django.test import SimpleTestCase, override_settings

from server.apps.basemaps.resolution import resolve_style
from server.apps.basemaps.seed_lib import HUTS_STYLE
from server.apps.basemaps.validation import validate_style_spec

TILE_ORIGIN = "{{env:MARTIN_TILE_URL}}"


def _style() -> dict[str, Any]:
    """A fresh minimal style with one MLT and one MVT vector source."""
    return {
        "version": 8,
        "sources": {
            "wd-huts": {
                "type": "vector",
                "tiles": [f"{TILE_ORIGIN}/huts/{{z}}/{{x}}/{{y}}.mlt"],
                "encoding": "mlt",
            },
            "wd-bookings": {
                "type": "vector",
                "tiles": [
                    (
                        f"{TILE_ORIGIN}/availability/{{z}}/{{x}}/{{y}}"
                        "?date={{date}}&days=4"
                    )
                ],
            },
        },
        "layers": [{"id": "wd-huts", "type": "circle", "source": "wd-huts"}],
    }


@pytest.mark.django_db
class EncodingPreservationTests:
    """`encoding` survives the serve-time pipeline (map-style-api delta).

    django_db: rendering resolves the tile-origin env token through the
    registry (the seeded ``MARTIN_TILE_URL`` row), not just settings.
    """

    @override_settings(MARTIN_TILE_URL="https://tiles.example.org")
    def test_resolved_mode_preserves_encoding(self):
        resolved = resolve_style(_style(), {"date": "2026-10-22"})
        huts = resolved["sources"]["wd-huts"]
        assert huts["encoding"] == "mlt"
        # ...and the .mlt tiles template is resolved to the tile origin
        assert huts["tiles"] == ["https://tiles.example.org/huts/{z}/{x}/{y}.mlt"]

    @override_settings(MARTIN_TILE_URL="https://tiles.example.org")
    def test_tokenized_mode_preserves_encoding(self):
        tokenized = resolve_style(_style(), {"date": "2026-10-22"}, tokenized=True)
        assert tokenized["sources"]["wd-huts"]["encoding"] == "mlt"

    @override_settings(MARTIN_TILE_URL="https://tiles.example.org")
    def test_absence_is_preserved(self):
        for tokenized in (False, True):
            resolved = resolve_style(
                _style(), {"date": "2026-10-22"}, tokenized=tokenized
            )
            assert "encoding" not in resolved["sources"]["wd-bookings"]


class SeedPairingTests(SimpleTestCase):
    """The huts overlay opts in; nothing else does — and the pairing is
    invariant (``.mlt`` template ⇔ ``encoding: mlt``)."""

    def test_huts_source_pairs_mlt_template_with_encoding(self):
        source = HUTS_STYLE["sources"]["wd-huts"]
        self.assertEqual(source["encoding"], "mlt")
        self.assertTrue(source["tiles"])
        for template in source["tiles"]:
            self.assertTrue(template.endswith(".mlt"), template)

    def test_other_sources_stay_mvt(self):
        for name, source in HUTS_STYLE["sources"].items():
            if name == "wd-huts":
                continue
            self.assertNotIn("encoding", source, name)
            for template in source.get("tiles", []):
                self.assertFalse(template.endswith(".mlt"), (name, template))

    def test_style_with_encoding_is_structurally_valid(self):
        # Validation is deliberately open (extra: allow) — the encoding
        # marker must pass MapLayer's save-time structural check.
        validate_style_spec(HUTS_STYLE)

    def test_huts_tiles_use_the_env_token(self):
        """Authored tile-origin URLs reference the registry token —
        no legacy placeholder in fresh seeds."""
        import json

        body = json.dumps(HUTS_STYLE)
        assert TILE_ORIGIN in body
        assert "{TILE_SERVER_URL}" not in body

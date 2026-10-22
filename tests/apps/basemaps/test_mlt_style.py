"""MLT opt-in: explicit ``.mlt`` URL space + ``encoding: mlt`` marker.

Covers the ``map-style-api`` delta (the rendering pipeline preserves a
vector source's ``encoding`` verbatim in resolved and tokenized modes,
never injects one) and the seed pairing contract for the huts overlay
(``.mlt`` tiles template always ships with ``encoding: mlt``; every other
vector source stays MVT — phase 1 scopes the Martin-side conversion to
the huts table source only).
"""

from __future__ import annotations

from django.test import SimpleTestCase, override_settings

from server.apps.basemaps.resolution import resolve_style
from server.apps.basemaps.seed_lib import HUTS_STYLE
from server.apps.basemaps.validation import validate_style_spec


def _style() -> dict:
    """A fresh minimal style with one MLT and one MVT vector source."""
    return {
        "version": 8,
        "sources": {
            "wd-huts": {
                "type": "vector",
                "tiles": ["{TILE_SERVER_URL}/huts/{z}/{x}/{y}.mlt"],
                "encoding": "mlt",
            },
            "wd-bookings": {
                "type": "vector",
                "tiles": [
                    "{TILE_SERVER_URL}/availability/{z}/{x}/{y}?date={{date}}&days=4"
                ],
            },
        },
        "layers": [{"id": "wd-huts", "type": "circle", "source": "wd-huts"}],
    }


class EncodingPreservationTests(SimpleTestCase):
    """`encoding` survives the serve-time pipeline (map-style-api delta)."""

    @override_settings(MARTIN_TILE_URL="https://tiles.example.org")
    def test_resolved_mode_preserves_encoding(self):
        resolved = resolve_style(_style(), {"date": "2026-10-22"})
        huts = resolved["sources"]["wd-huts"]
        self.assertEqual(huts["encoding"], "mlt")
        # ...and the .mlt tiles template is absolutized alongside it
        self.assertEqual(
            huts["tiles"],
            ["https://tiles.example.org/huts/{z}/{x}/{y}.mlt"],
        )

    @override_settings(MARTIN_TILE_URL="https://tiles.example.org")
    def test_tokenized_mode_preserves_encoding(self):
        tokenized = resolve_style(_style(), {"date": "2026-10-22"}, tokenized=True)
        self.assertEqual(tokenized["sources"]["wd-huts"]["encoding"], "mlt")

    @override_settings(MARTIN_TILE_URL="https://tiles.example.org")
    def test_absence_is_preserved(self):
        for tokenized in (False, True):
            with self.subTest(tokenized=tokenized):
                resolved = resolve_style(
                    _style(), {"date": "2026-10-22"}, tokenized=tokenized
                )
                self.assertNotIn("encoding", resolved["sources"]["wd-bookings"])


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

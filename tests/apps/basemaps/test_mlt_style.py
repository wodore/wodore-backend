"""MLT opt-in: explicit ``.mlt`` URL space + ``encoding: mlt`` marker.

Covers the ``map-style-api`` delta (the rendering pipeline preserves a
vector source's ``encoding`` verbatim in resolved and tokenized modes,
never injects one) and the seed pairing contract (``.mlt`` tiles
template always ships with ``encoding: mlt``): the huts overlay and the
availability overlay (``wd-bookings``, whose ``.mlt`` suffix sits before
the ``date``/``days`` query) both opt in; every other vector source
stays MVT.

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

#: Sources whose tile path (query stripped) ends in ``.mlt`` and that
#: therefore must carry ``encoding: mlt``.
MLT_SOURCES = ("wd-huts", "wd-bookings")


def _path_endswith_mlt(template: str) -> bool:
    """``.mlt`` selects MLT by path suffix only — a query string
    (``?date=…&days=4``) may follow it."""
    return template.split("?", 1)[0].endswith(".mlt")


def _style() -> dict[str, Any]:
    """A fresh minimal style with two MLT and one plain MVT source."""
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
                        f"{TILE_ORIGIN}/availability/{{z}}/{{x}}/{{y}}.mlt"
                        "?date={{date}}&days=4"
                    )
                ],
                "encoding": "mlt",
            },
            "wd-plain": {
                "type": "vector",
                "tiles": [f"{TILE_ORIGIN}/geoplaces/{{z}}/{{x}}/{{y}}"],
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
            assert "encoding" not in resolved["sources"]["wd-plain"]

    @override_settings(MARTIN_TILE_URL="https://tiles.example.org")
    def test_bookings_encoding_survives_with_query_template(self):
        """The availability source's marker survives resolution alongside
        its query-carrying template; the {{date}} token substitutes."""
        resolved = resolve_style(_style(), {"date": "2026-10-22"})
        bookings = resolved["sources"]["wd-bookings"]
        assert bookings["encoding"] == "mlt"
        assert bookings["tiles"] == [
            (
                "https://tiles.example.org/availability/{z}/{x}/{y}.mlt"
                "?date=2026-10-22&days=4"
            )
        ]


class SeedPairingTests(SimpleTestCase):
    """The huts and availability overlays opt in; nothing else does — and
    the pairing is invariant (``.mlt`` tiles path ⇔ ``encoding: mlt``)."""

    def test_mlt_sources_pair_template_with_encoding(self):
        for name in MLT_SOURCES:
            source = HUTS_STYLE["sources"][name]
            self.assertEqual(source["encoding"], "mlt", name)
            self.assertTrue(source["tiles"], name)
            for template in source["tiles"]:
                self.assertTrue(_path_endswith_mlt(template), (name, template))

    def test_bookings_template_keeps_query_after_suffix(self):
        """The .mlt suffix sits in the path; date/days stay a query."""
        template = HUTS_STYLE["sources"]["wd-bookings"]["tiles"][0]
        self.assertIn(".mlt?date={{date}}&days=4", template)

    def test_other_sources_stay_mvt(self):
        for name, source in HUTS_STYLE["sources"].items():
            if name in MLT_SOURCES:
                continue
            self.assertNotIn("encoding", source, name)
            for template in source.get("tiles", []):
                self.assertFalse(_path_endswith_mlt(template), (name, template))

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

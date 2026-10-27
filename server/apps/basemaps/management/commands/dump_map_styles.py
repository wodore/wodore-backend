"""Dump the seed's inline style documents to files (styl CI input).

The CI ``map-style-spec`` job validates every inline ``full`` seed style
against the real MapLibre style spec with the ``styl`` Rust binary
(github.com/navidabavi/styl). styl reads files, not Python objects —
this command walks the ``map_seed`` LAYERS definitions (no DB rows
needed; runs before any migrate) and writes one JSON per
``{slug}--{spec}--{profile}.json`` variant into the target directory.
Subset rows skip the dump — the pure-Python walker owns those (and runs
in the test suite); a subset document is a full style by construction,
so styl adds nothing there.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, override

from django.core.management.base import BaseCommand, CommandError

from server.apps.basemaps.management.commands.map_seed import LAYERS
from server.apps.basemaps.models import MapLayer


class Command(BaseCommand):
    """Write every inline full-profile seed style to an output directory."""

    help = (
        "Dump inline map seed styles to JSON files for external "
        "validation (styl). Usage: dump_map_styles --out DIR"
    )

    @override
    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--out",
            required=True,
            help="Target directory (created if missing)",
        )

    @override
    def handle(self, *args: Any, **options: Any) -> None:
        out = Path(str(options["out"]))
        out.mkdir(parents=True, exist_ok=True)
        written = 0
        for parent in LAYERS:
            variants = [parent, *parent.get("variants", [])]
            for variant in variants:
                style = (
                    variant.get("style")
                    if "style" in variant or "style_url" in variant
                    else parent.get("style")
                )
                if style is None:
                    continue
                profile = variant.get(
                    "profile", parent.get("profile", MapLayer.Profile.full)
                )
                if profile == MapLayer.Profile.subset:
                    continue  # walker-owned (test suite); no styl input
                spec = variant.get("spec", MapLayer.Spec.medium)
                name = f"{parent['slug']}--{spec}--{profile}.json"
                target = out / name
                target.write_text(json.dumps(style, indent=2, sort_keys=True))
                self.stdout.write(f"wrote {name}")
                written += 1
        if not written:
            raise CommandError("no inline full styles found to dump")
        self.stdout.write(self.style.SUCCESS(f"{written} style(s) dumped to {out}"))

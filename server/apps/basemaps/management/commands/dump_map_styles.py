"""Dump the seed's inline style documents to files (styl CI input).

The CI ``map-style-spec`` job validates every inline ``full`` seed style
against the real MapLibre style spec with the ``styl`` Rust binary
(github.com/navidnabi/styl). styl reads files, not Python objects —
this command walks the ``map_seed`` LAYERS definitions (no DB rows
needed; runs before any migrate) and writes one JSON per
``{slug}--{spec}--{profile}.json`` variant into the target directory.

Skip rules (single source of truth: the seed definitions):

* rows whose effective ``styl_ignored_rules == ["*"]`` (external-derived
  styles) skip the dump AND are listed in ``_skipped.txt`` — the CI
  workflow mirrors that manifest onto the static ``fixtures/styles/``
  files (which carry no seed metadata), so no hardcoded slug list
  lives in the workflow.

``profile=subset`` variants ARE dumped: a subset document is a full
  style by construction, and the CI ``map-style-spec`` job validates
every dumped file with BOTH the ``styl`` binary and the authoritative
``@maplibre/maplibre-gl-style-spec`` validator (the exact package the
frontend gates styles with — the 2026-11-06 staging incident shipped
an expression styl's ruleset does not implement, so styl alone passed
an invalid document).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, override

from django.core.management.base import BaseCommand, CommandError

from server.apps.basemaps.management.commands.map_seed import LAYERS, PARAMETERS
from server.apps.basemaps.models import MapLayer
from server.apps.basemaps.resolution import resolve_tokens

#: Parameter slug → seed default (scalars AND whole expression
#: subtrees — opacity-curve defaults are interpolate expressions). The
#: dump resolves parameter tokens so BOTH validators see the document
#: form the frontend validates: resolved (styl rejects unresolved
#: ``{{opacity}}`` strings with E018; the frontend's own gate resolves
#: with defaults ∪ overrides before validating). ``{{env:…}}`` tokens
#: embedded in URL strings are left for serving-time resolution — a
#: string is valid in any URL position.
_PARAMETER_DEFAULTS: dict[str, Any] = {
    param["slug"]: param["default"] for param in PARAMETERS
}


def _effective_styl_ignored(variant: dict[str, Any], parent: dict[str, Any]) -> Any:
    return variant.get("styl_ignored_rules", parent.get("styl_ignored_rules"))


class Command(BaseCommand):
    """Write every inline seed style (resolved) to an output directory."""

    help = (
        "Dump inline map seed styles (ALL profiles, parameter tokens "
        "resolved to their defaults) to JSON files for external "
        "validation (styl + @maplibre/maplibre-gl-style-spec); writes "
        "_skipped.txt with the styl-ignored slugs. "
        "Usage: dump_map_styles --out DIR"
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
        skipped: list[str] = []
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
                spec = variant.get("spec", MapLayer.Spec.medium)
                if _effective_styl_ignored(variant, parent) == ["*"]:
                    skipped.append(parent["slug"])
                    self.stdout.write(f"skipped (styl-ignored): {parent['slug']}")
                    continue
                name = f"{parent['slug']}--{spec}--{profile}.json"
                target = out / name
                resolved = resolve_tokens(style, _PARAMETER_DEFAULTS)
                target.write_text(json.dumps(resolved, indent=2, sort_keys=True))
                self.stdout.write(f"wrote {name}")
                written += 1
        (out / "_skipped.txt").write_text("\n".join(sorted(set(skipped))))
        if not written:
            raise CommandError("no inline seed styles found to dump")
        self.stdout.write(self.style.SUCCESS(f"{written} style(s) dumped to {out}"))

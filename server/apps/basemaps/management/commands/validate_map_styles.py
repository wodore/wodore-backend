"""Sweep every inline map style row against its profile's rules.

The subset walker and styl gate interactive edits (``MapLayer.clean()``)
and the seed upsert directly — but ORM writes
(``objects.create``/``update``) bypass both. This command is the CI
sweep (openspec style-profiles-subset D6): every ``profile=subset`` row
must pass the subset walker, every inline row the structural checks,
every inline row must carry its rules ``version``, and — when a styl
binary is on PATH — styl E-codes (minus each row's ignore list) fail
the sweep while W-codes are always reported. Nonzero exit names every
drift. Absent binary: styl silently skips (the CI tests job never
requires it).
"""

from __future__ import annotations

from typing import Any, override

from django.core.management.base import BaseCommand, CommandError

from server.apps.basemaps.models import MapLayer
from server.apps.basemaps.validation import (
    StyleValidationError,
    run_styl,
    validate_subset_style,
)
from server.apps.basemaps.validation import validate_style_spec as structural


class Command(BaseCommand):
    """Validate inline style documents of all active map layers."""

    help = (
        "Sweep inline map styles: structural checks for every row, the "
        "subset whitelist for profile=subset rows, version presence for "
        "inline rows, styl E-codes (when the binary is on PATH). "
        "Fails nonzero naming every violation."
    )

    @override
    def handle(self, *args: Any, **options: Any) -> None:
        failures: list[str] = []
        styl_ran = 0
        layers = MapLayer.objects.filter(is_active=True, style__isnull=False).order_by(
            "slug", "spec", "profile"
        )
        for layer in layers:
            label = f"{layer.slug} [{layer.spec}/{layer.profile}]"
            style = layer.style
            if style is None:  # the queryset filters style__isnull=False
                continue
            try:
                structural(style)
                if layer.profile == MapLayer.Profile.subset:
                    validate_subset_style(style)
            except StyleValidationError as exc:
                failures.append(f"{label}: {exc}")
                continue
            if not layer.version:
                failures.append(f"{label}: inline styles need a rules version")
            styl_result = run_styl(style, ignored_rules=layer.styl_ignored_rules or ())
            if styl_result is None:
                continue
            styl_ran += 1
            if styl_result.errors:
                failures.append(f"{label}: styl: {'; '.join(styl_result.errors)}")
            # W-codes never block — but the sweep always surfaces them.
            for warning in styl_result.warnings:
                self.stdout.write(f"warning: {label}: styl: {warning}")
        if failures:
            for failure in failures:
                self.stderr.write(failure)
            count = len(failures)
            raise CommandError(f"{count} style violation(s)")
        total = layers.count()
        self.stdout.write(f"all {total} inline style(s) valid (styl ran on {styl_ran})")

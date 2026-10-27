"""Sweep every inline map style row against its profile's rules.

The subset walker gates interactive edits (``MapLayer.clean()``) and the
seed upsert directly — but ORM writes (``objects.create``/``update``)
bypass both. This command is the CI sweep (openspec
style-profiles-subset D6): every ``profile=subset`` row must pass the
subset walker, every inline row the structural checks, and every inline
row must carry its rules ``version``. Nonzero exit names every drift.
"""

from __future__ import annotations

from typing import Any, override

from django.core.management.base import BaseCommand, CommandError

from server.apps.basemaps.models import MapLayer
from server.apps.basemaps.validation import StyleValidationError, validate_subset_style
from server.apps.basemaps.validation import validate_style_spec as structural


class Command(BaseCommand):
    """Validate inline style documents of all active map layers."""

    help = (
        "Sweep inline map styles: structural checks for every row, the "
        "subset whitelist for profile=subset rows, version presence for "
        "inline rows. Fails nonzero naming every violation."
    )

    @override
    def handle(self, *args: Any, **options: Any) -> None:
        failures: list[str] = []
        layers = MapLayer.objects.filter(is_active=True, style__isnull=False).order_by(
            "slug", "spec", "profile"
        )
        for layer in layers:
            label = f"{layer.slug} [{layer.spec}/{layer.profile}]"
            try:
                structural(layer.style)
                if layer.profile == MapLayer.Profile.subset:
                    validate_subset_style(layer.style)
            except StyleValidationError as exc:
                failures.append(f"{label}: {exc}")
                continue
            if not layer.version:
                failures.append(f"{label}: inline styles need a rules version")
        if failures:
            for failure in failures:
                self.stderr.write(failure)
            count = len(failures)
            raise CommandError(f"{count} style violation(s)")
        total = layers.count()
        self.stdout.write(f"all {total} inline style(s) valid")

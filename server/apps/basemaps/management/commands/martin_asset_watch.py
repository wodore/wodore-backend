"""Observe Martin's served sprites/fonts and publish content versions.

Thin wrapper around ``basemaps.tile_assets.run_martin_watcher`` — the
logic lives in a module-level callable so django-q2 ``Schedule.func``
can point at it directly.
"""

from __future__ import annotations

from typing import Any, override

from django.core.management.base import BaseCommand

from server.apps.basemaps.tile_assets import run_martin_watcher


class Command(BaseCommand):
    help = (
        "Probe the sprite/font endpoints the served styles actually "
        "reference (with a cache-busting nonce) and publish their "
        "content hash to the TileAssetVersion registry when it changed."
    )

    @override
    def handle(self, *args: Any, **options: Any) -> None:
        stats = run_martin_watcher()
        self.stdout.write(
            f"published={stats['published']} kept={stats['kept']} "
            f"failed={stats['failed']}"
        )

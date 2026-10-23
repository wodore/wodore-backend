"""Daily conditional-GET verification of external asset registry entries.

Thin wrapper around ``basemaps.tile_assets.run_external_verifier`` — the
logic lives in a module-level callable so django-q2 ``Schedule.func``
can point at it directly.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from server.apps.basemaps.tile_assets import run_external_verifier


class Command(BaseCommand):
    help = (
        "Verify external asset URLs referenced by active layers with "
        "conditional GETs (If-None-Match / If-Modified-Since, falling "
        "back to body hashing) and bump their registry versions on change."
    )

    def handle(self, *args, **options):
        stats = run_external_verifier()
        self.stdout.write(
            f"changed={stats['changed']} unchanged={stats['unchanged']} "
            f"failed={stats['failed']} skipped={stats['skipped']}"
        )

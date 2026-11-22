"""Export DB basemap styles back to fixture files for committing.

The admin edit → preview → save → export → commit workflow: edit a
basemap style in the admin (with live MapLibre preview + linting),
save the row, then run this command to write the updated style back
to ``fixtures/styles/{slug}.json`` — a git-diffable file you commit
to update the seed source of truth.

Usage::

    app map_export_fixtures                    # all basemaps with inline styles
    app map_export_fixtures --slug wd-outdoor-base-mtk-hill   # one basemap
    app map_export_fixtures --out custom/dir   # write to a different directory

The output format matches the existing fixtures (indent 2, sorted
keys, trailing newline) so the git diff is minimal.
"""

import json
from pathlib import Path
from typing import Any, override

from django_admin_runner import register_command

from django.core.management.base import BaseCommand, CommandParser

from server.apps.basemaps.models import MapLayer


@register_command(group="Basemaps")
class Command(BaseCommand):
    help = (
        "Export basemap styles from the database back to fixture files. "
        "Edit in the admin, then run this to get a commitable diff."
    )

    @override
    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--slug",
            type=str,
            default=None,
            help="Export one basemap by slug (default: all with inline styles).",
        )
        parser.add_argument(
            "--out",
            type=str,
            default=None,
            help="Output directory (default: server/apps/basemaps/fixtures/styles).",
        )
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="Overwrite existing fixture files (default: only write if the DB differs).",
        )

    @override
    def handle(self, *args: Any, **options: Any) -> None:
        slug = options.get("slug")
        out_dir = Path(options.get("out") or "server/apps/basemaps/fixtures/styles")
        overwrite = options.get("overwrite", False)

        rows = MapLayer.objects.filter(
            role=MapLayer.Role.basemap,
            is_active=True,
            style__isnull=False,
        ).order_by("slug")

        if slug:
            rows = rows.filter(slug=slug)

        if not rows.exists():
            self.stdout.write(
                self.style.WARNING("No basemap rows with inline styles found.")
            )
            return

        out_dir.mkdir(parents=True, exist_ok=True)
        written = 0
        unchanged = 0

        for row in rows:
            target = out_dir / f"{row.slug}.json"
            content = json.dumps(row.style, indent=2, sort_keys=True) + "\n"

            if target.exists() and not overwrite:
                existing = target.read_text()
                if existing == content:
                    unchanged += 1
                    continue

            target.write_text(content)
            self.stdout.write(self.style.SUCCESS(f"wrote {target}"))
            written += 1

        if unchanged:
            self.stdout.write(
                f"{unchanged} file(s) unchanged (use --overwrite to force)."
            )
        if written:
            self.stdout.write(
                self.style.SUCCESS(f"{written} fixture file(s) written to {out_dir}")
            )
        else:
            self.stdout.write("No changes needed — DB matches fixtures.")

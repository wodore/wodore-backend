"""Move hut availability history into the place table.

Geoplace-availability change, Phase B (design D6): idempotent by natural key
``(geo_place, availability_date, first_checked)``, resumable by source-id
ranges, chunked — enqueues django-q tasks by default; ``--sync`` runs
inline. Never copies hut PKs; never orders semantically by id. Snapshots the
max source id + epoch start so events at/after the start are never moved.

    python manage.py move_availability_history --dry-run
    python manage.py move_availability_history --sync
    python manage.py move_availability_history            # django-q chunks
"""

from typing import Any, override

from django.core.management.base import BaseCommand, CommandParser

from ...history_move import DEFAULT_BATCH_SIZE, chunk_ranges, move_chunk, snapshot


class Command(BaseCommand):
    help = (
        "Move HutAvailabilityHistory into GeoPlaceAvailabilityHistory "
        "(idempotent, resumable; see geoplace-availability design D6)"
    )

    @override
    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be moved without writing",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=DEFAULT_BATCH_SIZE,
            help=f"Source-id rows per chunk (default {DEFAULT_BATCH_SIZE})",
        )
        parser.add_argument(
            "--min-id",
            type=int,
            default=0,
            help="Lower source-id bound (exclusive) — resume/partial-run cursor",
        )
        parser.add_argument(
            "--max-id",
            type=int,
            default=None,
            help="Upper source-id bound (inclusive); default: current max",
        )
        parser.add_argument(
            "--sync",
            action="store_true",
            help="Run chunks inline instead of enqueueing django-q tasks",
        )

    @override
    def handle(self, *args: Any, **options: Any) -> None:
        dry_run = options["dry_run"]
        # --dry-run implies --sync (A–C review nit): enqueuing no-op
        # django-q workers would report nothing to the console.
        if dry_run and not options["sync"]:
            options["sync"] = True
            self.stdout.write("--dry-run implies --sync (no tasks are enqueued)")
        max_id, started_at = snapshot()
        if max_id == 0:
            self.stdout.write("No hut availability history rows — nothing to move.")
            return

        hi_bound = options["max_id"] if options["max_id"] is not None else max_id
        ranges = chunk_ranges(
            hi_bound, options["batch_size"], id_from=options["min_id"]
        )
        prefix = "[DRY RUN] " if dry_run else ""
        self.stdout.write(
            f"{prefix}Moving history up to source id {hi_bound} "
            f"(epoch start {started_at.isoformat()}), "
            f"{len(ranges)} chunk(s) of ≤{options['batch_size']}"
        )

        if options["sync"]:
            totals = {"moved": 0, "skipped_existing": 0, "availability_missing": 0}
            unmatched: list[str] = []
            for lo, hi in ranges:
                stats = move_chunk(lo, hi, started_at, dry_run=dry_run)
                totals["moved"] += stats["moved"]
                totals["skipped_existing"] += stats["skipped_existing"]
                totals["availability_missing"] += stats["availability_missing"]
                for slug in stats["unmatched"]:
                    if slug not in unmatched:
                        unmatched.append(slug)
                self.stdout.write(
                    f"  chunk ({lo}, {hi}]: moved={stats['moved']} "
                    f"skipped={stats['skipped_existing']} "
                    f"unmatched={len(stats['unmatched'])}"
                )
            self.stdout.write(
                f"{prefix}Done: moved={totals['moved']} "
                f"skipped_existing={totals['skipped_existing']} "
                f"availability_missing={totals['availability_missing']}; "
                f"unmatched huts: {', '.join(unmatched) or '-'}"
            )
            return

        from django_q.tasks import async_task

        for lo, hi in ranges:
            async_task(
                "server.apps.availability.history_move.run_chunk",
                lo,
                hi,
                started_at.isoformat(),
                dry_run,
            )
        self.stdout.write(
            f"Enqueued {len(ranges)} django-q task(s). "
            "Re-run with --sync to verify (idempotent) or check the q admin."
        )

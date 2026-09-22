"""
Management command to update hut availability data.

Usage:
    python manage.py update_availability                    # Update based on priority
    python manage.py update_availability --all               # Force update all huts
    python manage.py update_availability --hut-slug <slug>   # Update specific hut
    python manage.py update_availability --dry-run           # Show what would be updated
"""

import click
from django_admin_runner import register_command
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from server.apps.huts.models import Hut

from ...models import HutAvailability
from ...services import SERVICES, AvailabilityService

# availability sources that provide booking data (slug -> service)
BOOKING_SOURCES = [
    slug for slug, service in SERVICES.items() if service.support_booking
]


@register_command(group="Availability")
def _hut_source_str(hut: "Hut") -> str:
    """Availability source slug of a hut (for display; needs select_related)."""
    return hut.availability_source_ref.slug if hut.availability_source_ref else "-"


class Command(BaseCommand):
    help = "Update hut availability data from booking sources"

    def add_arguments(self, parser):
        parser.add_argument(
            "--hut-slug",
            type=str,
            help="Update specific hut by slug",
        )
        parser.add_argument(
            "--hut-id",
            type=int,
            help="Update specific hut by ID",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Force update all huts with booking references",
        )
        parser.add_argument(
            "-s",
            "--source",
            default="all",
            choices=["all"] + BOOKING_SOURCES,
            help="Only update huts of this availability source (default: all)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be updated without making changes",
        )
        parser.add_argument(
            "--days",
            type=int,
            default=365,
            help="Number of days to fetch (default: 365)",
        )
        parser.add_argument(
            "--request-interval",
            type=float,
            default=0.1,
            help="Time in seconds between requests (default: 0.1)",
        )
        parser.add_argument(
            "--profile",
            action="store_true",
            help="Enable profiling to identify performance bottlenecks",
        )
        parser.add_argument(
            "--no-progress",
            action="store_true",
            help="Disable progress bar and print results as they complete (useful for cron jobs)",
        )
        # Priority configuration
        parser.add_argument(
            "--high-priority-minutes",
            type=int,
            help="Minutes between checks for high/full occupancy (default from settings)",
        )
        parser.add_argument(
            "--medium-priority-minutes",
            type=int,
            help="Minutes between checks for medium occupancy (default from settings)",
        )
        parser.add_argument(
            "--low-priority-minutes",
            type=int,
            help="Minutes between checks for low/empty occupancy (default from settings)",
        )
        parser.add_argument(
            "--inactive-priority-minutes",
            type=int,
            help="Minutes between checks for unknown status (default from settings)",
        )
        parser.add_argument(
            "--next-days",
            type=int,
            help="Number of days in the future to consider for priority selection (default from settings)",
        )

    def handle(self, *args, **options):
        profile_enabled = options.get("profile")
        profiler = None
        if profile_enabled:
            import cProfile

            profiler = cProfile.Profile()
            profiler.enable()

        try:
            self._handle_update(*args, **options)
        finally:
            if profiler is not None:
                import pstats
                from io import StringIO

                profiler.disable()

                # Sort by cumulative time
                s = StringIO()
                stats = pstats.Stats(profiler, stream=s)
                stats.strip_dirs()
                stats.sort_stats("cumulative")
                stats.print_stats(30)  # Top 30 functions
                click.echo(s.getvalue())

                # Also show time-sorted
                click.echo("\n" + "-" * 80)
                click.secho("BY TOTAL TIME", fg="cyan", bold=True)
                click.echo("-" * 80 + "\n")
                s = StringIO()
                stats = pstats.Stats(profiler, stream=s)
                stats.strip_dirs()
                stats.sort_stats("time")
                stats.print_stats(30)
                click.echo(s.getvalue())

    def _handle_update(self, *args, **options):
        hut_slug = options.get("hut_slug")
        hut_id = options.get("hut_id")
        update_all = options.get("all")
        dry_run = options.get("dry_run")
        days = options.get("days") or 365
        request_interval = options.get("request_interval") or 0.1
        no_progress = options.get("no_progress")
        source = (options.get("source") or "all").strip().lower()

        # Priority parameters
        high_priority_minutes = options.get("high_priority_minutes")
        medium_priority_minutes = options.get("medium_priority_minutes")
        low_priority_minutes = options.get("low_priority_minutes")
        inactive_priority_minutes = options.get("inactive_priority_minutes")
        next_days = options.get("next_days")

        click.secho("\n=== Hut Availability Update ===\n", fg="cyan", bold=True)
        label = f" of source '{source}'" if source != "all" else ""

        # Determine which huts to update
        if hut_slug:
            huts = Hut.objects.filter(slug=hut_slug).select_related(
                "availability_source_ref"
            )
            if not huts.exists():
                click.secho(f"Error: Hut with slug '{hut_slug}' not found", fg="red")
                return
            click.echo(f"Updating hut: {hut_slug}")
        elif hut_id:
            huts = Hut.objects.filter(id=hut_id).select_related(
                "availability_source_ref"
            )
            if not huts.exists():
                click.secho(f"Error: Hut with ID '{hut_id}' not found", fg="red")
                return
            click.echo(f"Updating hut ID: {hut_id}")
        elif update_all:
            huts = Hut.objects.filter(
                availability_source_ref__isnull=False
            ).select_related("availability_source_ref")
            if source != "all":
                huts = huts.filter(availability_source_ref__slug=source)
            click.echo(
                f"Updating all {huts.count()} huts with availability sources{label}"
            )
        else:
            # Default: Use priority-based selection + new huts
            click.echo("Using priority-based selection (includes new huts)")
            huts = HutAvailability.objects.get_huts_needing_update(
                high_priority_minutes=high_priority_minutes,
                medium_priority_minutes=medium_priority_minutes,
                low_priority_minutes=low_priority_minutes,
                inactive_priority_minutes=inactive_priority_minutes,
                next_days=next_days,
            )
            huts = huts.select_related("availability_source_ref")
            if source != "all":
                huts = huts.filter(availability_source_ref__slug=source)
            hut_count = huts.count()
            click.echo(f"Found {hut_count} hut(s) needing updates{label}")

        if dry_run:
            click.secho("\n[DRY RUN MODE - No changes will be made]\n", fg="yellow")

        # Fetch booking data using batch update
        huts_to_update = list(huts)
        source_by_slug = {h.slug: _hut_source_str(h) for h in huts_to_update}
        if not huts_to_update:
            click.secho("No huts to update", fg="yellow")
            return

        click.echo(f"\nFetching availability for {len(huts_to_update)} hut(s)...\n")

        # Estimate time for external fetches
        effective_interval = max(request_interval, 0.25)  # Minimum 250ms per request
        estimated_seconds = len(huts_to_update) * effective_interval
        if estimated_seconds > 60:
            click.echo(f"Estimated fetch time: ~{estimated_seconds / 60:.1f} minutes")
        else:
            click.echo(f"Estimated fetch time: ~{estimated_seconds:.0f} seconds")
        click.echo()

        failed_results: list[tuple] = []
        stats = {
            "huts_processed": 0,
            "huts_failed": 0,
            "records_created": 0,
            "records_updated": 0,
            "history_entries": 0,
        }

        start_time = timezone.now()

        if dry_run:
            for hut in huts_to_update:
                click.secho(f"  Would update: {hut.name} ({hut.slug})", fg="cyan")
        else:
            # Use batch update for efficiency (single external service call for all huts)
            # Note: If we have multiple services in the future, we could fetch them in parallel
            # using threading/async to further improve performance

            # Calculate batch information
            batch_size = 30  # Should match service default
            total_batches = (
                len(huts_to_update) + batch_size - 1
            ) // batch_size  # Ceiling division

            if no_progress:
                # No progress bar - print results as they complete
                hut_counter = {"fetch": 0, "process": 0}

                def fetch_callback():
                    hut_counter["fetch"] += 1
                    current_batch = ((hut_counter["fetch"] - 1) // batch_size) + 1
                    # Get current hut info
                    current_hut = huts_to_update[hut_counter["fetch"] - 1]
                    hut_info = (
                        f"{current_hut.name} ({current_hut.slug}) "
                        f"[{source_by_slug.get(current_hut.slug, '-')}]{label}"
                    )
                    click.echo(
                        f"[{hut_counter['fetch']}/{len(huts_to_update)}] "
                        f"Batch {current_batch}/{total_batches} - "
                        f"Fetching {hut_info}..."
                    )

                def process_callback():
                    hut_counter["process"] += 1
                    current_batch = ((hut_counter["process"] - 1) // batch_size) + 1
                    # Get current hut info
                    current_hut = huts_to_update[hut_counter["process"] - 1]
                    hut_info = (
                        f"{current_hut.name} ({current_hut.slug}) "
                        f"[{source_by_slug.get(current_hut.slug, '-')}]{label}"
                    )
                    click.echo(
                        f"[{hut_counter['process']}/{len(huts_to_update)}] "
                        f"Batch {current_batch}/{total_batches} - "
                        f"Saving {hut_info}..."
                    )

                # Run batch update with callbacks
                batch_result = AvailabilityService.update_huts_availability(
                    huts=huts_to_update,
                    days=days,
                    request_interval=request_interval,
                    fetch_progress_callback=fetch_callback,
                    process_progress_callback=process_callback,
                )
            else:
                # Use progress bar
                current_batch = {
                    "fetch": 0,
                    "process": 0,
                }  # Track batch for each operation

                with Progress(
                    SpinnerColumn(finished_text="✓"),
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(),
                    TaskProgressColumn(),
                    TextColumn("•"),
                    TimeElapsedColumn(),
                    TextColumn("{task.fields[status]}"),
                ) as progress:
                    # Create progress tasks
                    fetch_task = progress.add_task(
                        "[cyan]Fetching from external API...",
                        total=len(huts_to_update),
                        status=f"[cyan]Batch 1/{total_batches}",
                    )
                    process_task = progress.add_task(
                        "[green]Saving to database...",
                        total=len(huts_to_update),
                        status="[dim]Waiting...",
                    )

                    def fetch_callback():
                        progress.advance(fetch_task)
                        # Update batch info when we move to next batch
                        current_hut = progress.tasks[fetch_task].completed or 0
                        new_batch = (current_hut // batch_size) + 1
                        if new_batch != current_batch["fetch"]:
                            current_batch["fetch"] = new_batch
                            # Update fetch status
                            progress.update(
                                fetch_task,
                                status=f"[cyan]Batch {new_batch}/{total_batches}",
                            )
                            # Set process to waiting for next batch
                            if new_batch <= total_batches:
                                progress.update(
                                    process_task,
                                    status="[dim]Waiting...",
                                )

                    def process_callback():
                        progress.advance(process_task)
                        # Update batch info when we move to next batch
                        current_hut = progress.tasks[process_task].completed or 0
                        new_batch = (current_hut // batch_size) + 1

                        # Update process status to show current batch
                        if new_batch != current_batch["process"]:
                            current_batch["process"] = new_batch

                        progress.update(
                            process_task,
                            status=f"[green]Batch {new_batch}/{total_batches}",
                        )

                    # Run batch update with both progress callbacks
                    batch_result = AvailabilityService.update_huts_availability(
                        huts=huts_to_update,
                        days=days,
                        request_interval=request_interval,
                        fetch_progress_callback=fetch_callback,
                        process_progress_callback=process_callback,
                    )

            # Display results
            click.echo()
            for result in batch_result.results:
                stats["huts_processed"] += 1

                # Find the hut object for display
                hut = next(
                    (h for h in huts_to_update if h.slug == result.hut_slug), None
                )
                hut_name = hut.name if hut else result.hut_slug

                src = source_by_slug.get(result.hut_slug, "-")
                click.echo(
                    f"{stats['huts_processed']:3d}. {hut_name} ({result.hut_slug}) [{src}]...",
                    nl=False,
                )

                if result.success:
                    stats["records_created"] += result.records_created
                    stats["records_updated"] += result.records_updated
                    stats["history_entries"] += result.history_entries

                    click.secho(
                        f" ✓ {result.records_created} created, {result.records_updated} updated, {result.history_entries} history",
                        fg="green",
                    )
                else:
                    stats["huts_failed"] += 1
                    # Determine color based on error type
                    color = (
                        "yellow"
                        if "empty result" in (result.error_message or "").lower()
                        or "no booking data" in (result.error_message or "").lower()
                        else "red"
                    )
                    click.secho(f" ✗ {result.error_message}", fg=color)
                    failed_results.append((result, src))

        end_time = timezone.now()
        duration = (end_time - start_time).total_seconds()

        # Print summary
        click.secho("\n=== Summary ===", fg="cyan", bold=True)
        click.echo(f"Duration: {duration:.2f} seconds")
        click.echo(f"Huts processed: {stats['huts_processed']}")
        click.echo(f"Huts failed: {stats['huts_failed']}")
        click.echo(f"Records created: {stats['records_created']}")
        click.echo(f"Records updated: {stats['records_updated']}")
        click.echo(f"History entries: {stats['history_entries']}")

        if dry_run:
            click.secho("\n[DRY RUN - No changes were made]", fg="yellow")
            return

        if failed_results:
            click.secho(
                f"\nFailed huts ({len(failed_results)} of {stats['huts_processed']}):",
                fg="yellow",
                bold=True,
            )
            for result, src in failed_results:
                click.echo(f"  {result.hut_slug} [{src}]: {result.error_message}")

        # Complete failure (e.g. source API down) is a real error -> raise.
        # Partial failures (closed/between-season huts) are expected and only listed.
        if (
            stats["huts_processed"] > 0
            and stats["huts_failed"] == stats["huts_processed"]
        ):
            raise CommandError(
                f"All {stats['huts_failed']} hut(s) failed"
                + (f" (source '{source}')" if source != "all" else "")
            )

"""
Management command to update hut availability data.

Usage:
    python manage.py update_availability                    # Update based on priority
    python manage.py update_availability --all               # Force update all huts
    python manage.py update_availability --hut-slug <slug>   # Update specific hut
    python manage.py update_availability --dry-run           # Show what would be updated
"""

import click

from django.core.management.base import BaseCommand
from django.utils import timezone

from server.apps.huts.models import Hut

from ...models import HutAvailability
from ...services import AvailabilityService


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

    def handle(self, *args, **options):
        hut_slug = options.get("hut_slug")
        hut_id = options.get("hut_id")
        update_all = options.get("all")
        dry_run = options.get("dry_run")
        days = options.get("days")
        request_interval = options.get("request_interval")

        click.secho("\n=== Hut Availability Update ===\n", fg="cyan", bold=True)

        # Determine which huts to update
        if hut_slug:
            huts = Hut.objects.filter(slug=hut_slug)
            if not huts.exists():
                click.secho(f"Error: Hut with slug '{hut_slug}' not found", fg="red")
                return
            click.echo(f"Updating hut: {hut_slug}")
        elif hut_id:
            huts = Hut.objects.filter(id=hut_id)
            if not huts.exists():
                click.secho(f"Error: Hut with ID '{hut_id}' not found", fg="red")
                return
            click.echo(f"Updating hut ID: {hut_id}")
        elif update_all:
            huts = Hut.objects.filter(booking_ref__isnull=False)
            click.echo(f"Updating all {huts.count()} huts with booking references")
        else:
            # Default: Use priority-based selection + new huts
            click.echo("Using priority-based selection (includes new huts)")
            huts = HutAvailability.objects.get_huts_needing_update()
            hut_count = huts.count()
            click.echo(f"Found {hut_count} hut(s) needing updates")

        if dry_run:
            click.secho("\n[DRY RUN MODE - No changes will be made]\n", fg="yellow")

        # Fetch booking data using Hut.get_bookings
        huts_to_update = list(huts)
        if not huts_to_update:
            click.secho("No huts to update", fg="yellow")
            return

        click.echo(f"\nFetching availability for {len(huts_to_update)} hut(s)...\n")

        stats = {
            "huts_processed": 0,
            "huts_failed": 0,
            "records_created": 0,
            "records_updated": 0,
            "history_entries": 0,
        }

        start_time = timezone.now()

        for hut in huts_to_update:
            stats["huts_processed"] += 1
            click.echo(
                f"{stats['huts_processed']:3d}. Processing: {hut.name} ({hut.slug})...",
                nl=False,
            )

            if dry_run:
                click.secho(" Would update availability", fg="cyan")
                continue

            # Use the service to update availability
            result = AvailabilityService.update_hut_availability(
                hut=hut,
                days=days,
                request_interval=request_interval,
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
                    if "empty result" in (result.error_message or "")
                    else "red"
                )
                click.secho(f" {result.error_message}", fg=color)

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

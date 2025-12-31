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
from django.db import transaction
from django.utils import timezone

from server.apps.huts.models import Hut, HutType
from server.apps.organizations.models import Organization

from ...models import AvailabilityStatus, HutAvailability, HutAvailabilityHistory


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
            try:
                stats["huts_processed"] += 1
                click.echo(
                    f"{stats['huts_processed']:3d}. Processing: {hut.name} ({hut.slug})...",
                    nl=False,
                )

                # Use the existing Hut.get_bookings method
                try:
                    bookings_data = Hut.get_bookings(
                        hut_slugs=[hut.slug],
                        date="now",
                        days=days,
                        request_interval=request_interval,
                    )
                except Exception as booking_error:
                    click.secho(
                        f" Error fetching bookings: {str(booking_error)}", fg="red"
                    )
                    stats["huts_failed"] += 1
                    # Mark failure in AvailabilityStatus
                    status, _ = AvailabilityStatus.objects.get_or_create(hut=hut)
                    status.mark_failure()
                    continue

                if not bookings_data:
                    click.secho(" No booking data returned (empty result)", fg="yellow")
                    stats["huts_failed"] += 1
                    # Mark failure in AvailabilityStatus (empty data)
                    status, _ = AvailabilityStatus.objects.get_or_create(hut=hut)
                    status.mark_failure()
                    continue

                hut_booking = bookings_data[0]
                source_org = Organization.objects.get(slug=hut_booking.source)
                # Use hut_id as source_id (the ID in the booking system)
                source_hut_id = str(hut_booking.hut_id)

                if dry_run:
                    click.secho(
                        f" Would process {len(hut_booking.bookings)} dates",
                        fg="cyan",
                    )
                    continue

                # Process each booking date
                created_count = 0
                updated_count = 0
                history_count = 0

                for booking in hut_booking.bookings:
                    # Extract all fields from HutBookingSchema
                    reservation_status = (
                        booking.reservation_status.value
                        if hasattr(booking.reservation_status, "value")
                        else str(booking.reservation_status)
                    )
                    occupancy_status = (
                        booking.occupancy_status.value
                        if hasattr(booking.occupancy_status, "value")
                        else str(booking.occupancy_status)
                    )

                    # Get hut_type FK object
                    hut_type_obj = None
                    if booking.hut_type:
                        hut_type_obj = HutType.values.get(booking.hut_type)

                    now = timezone.now()

                    # Get or create with atomic transaction
                    with transaction.atomic():
                        availability, created = HutAvailability.objects.get_or_create(
                            hut=hut,
                            availability_date=booking.date,
                            defaults={
                                "source_organization": source_org,
                                "source_id": source_hut_id,
                                "free": booking.free,
                                "total": booking.total,
                                "occupancy_percent": booking.occupancy_percent,
                                "occupancy_steps": booking.occupancy_steps,
                                "occupancy_status": occupancy_status,
                                "reservation_status": reservation_status,
                                "link": booking.link or "",
                                "hut_type": hut_type_obj,
                                "first_checked": now,
                                "last_checked": now,
                            },
                        )

                        if created:
                            created_count += 1
                            # Create initial history entry (minimal fields only)
                            HutAvailabilityHistory.objects.create(
                                availability=availability,
                                hut=hut,
                                availability_date=booking.date,
                                free=booking.free,
                                total=booking.total,
                                occupancy_percent=booking.occupancy_percent,
                                occupancy_status=occupancy_status,
                                reservation_status=reservation_status,
                                hut_type=hut_type_obj,
                                first_checked=now,
                                last_checked=now,
                            )
                            history_count += 1
                        else:
                            # Check if data changed
                            changed, history = availability.update_availability(
                                free=booking.free,
                                total=booking.total,
                                occupancy_percent=booking.occupancy_percent,
                                occupancy_steps=booking.occupancy_steps,
                                occupancy_status=occupancy_status,
                                reservation_status=reservation_status,
                                link=booking.link or "",
                                hut_type=hut_type_obj,
                            )
                            if changed:
                                updated_count += 1
                                if history:
                                    history_count += 1

                stats["records_created"] += created_count
                stats["records_updated"] += updated_count
                stats["history_entries"] += history_count

                # Mark success in AvailabilityStatus
                status, _ = AvailabilityStatus.objects.get_or_create(hut=hut)
                status.mark_success()

                click.secho(
                    f" ✓ {created_count} created, {updated_count} updated, {history_count} history",
                    fg="green",
                )

            except Exception as e:
                stats["huts_failed"] += 1
                click.secho(f" ✗ Failed: {str(e)}", fg="red")

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

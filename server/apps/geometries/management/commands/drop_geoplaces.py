"""
Management command to drop GeoPlace data.

Allows selective deletion by country code with safety confirmations.

Usage:
    app drop_geoplaces --all                        # Drop all geoplaces (requires confirmation)
    app drop_geoplaces -c ch                        # Drop Swiss geoplaces
    app drop_geoplaces -c ch,de                     # Drop Swiss and German geoplaces
    app drop_geoplaces -c alps                      # Drop all Alpine country geoplaces
    app drop_geoplaces -c ch --force                # Skip confirmation prompt
"""

from django.core.management.base import BaseCommand, CommandParser

from server.apps.external_geonames.management.commands._country_groups import (
    expand_countries,
)
from server.apps.geometries.models import GeoPlace


class Command(BaseCommand):
    help = "Drop GeoPlace data with optional country filtering"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "-c",
            "--countries",
            type=str,
            help="Comma-separated country codes or group name (e.g., 'ch,de' or 'alps')",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Drop all geoplaces (cannot be combined with --countries)",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Skip confirmation prompt",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be deleted without actually deleting",
        )

    def handle(self, *args, **options) -> None:
        countries = (
            expand_countries(options["countries"]) if options["countries"] else None
        )
        drop_all = options["all"]
        force = options["force"]
        dry_run = options["dry_run"]

        # Validation
        if drop_all and countries:
            self.stdout.write(
                self.style.ERROR(
                    "Cannot use --all with --countries. Choose one or the other."
                )
            )
            return

        if not drop_all and not countries:
            self.stdout.write(
                self.style.ERROR(
                    "Must specify either --all or --countries to delete geoplaces."
                )
            )
            return

        # Build queryset
        if drop_all:
            queryset = GeoPlace.objects.all()
            description = "ALL geoplaces"
        else:
            queryset = GeoPlace.objects.filter(country_code__in=countries)
            description = f"geoplaces from countries: {', '.join(countries)}"

        count = queryset.count()

        if count == 0:
            self.stdout.write(self.style.WARNING(f"No {description} found to delete."))
            return

        # Show what will be deleted
        if dry_run:
            self.stdout.write(
                self.style.WARNING(f"[DRY RUN] Would delete {count} {description}")
            )
            # Show breakdown by country
            by_country = (
                queryset.values("country_code")
                .annotate(
                    count=__import__("django.db.models", fromlist=["Count"]).Count("id")
                )
                .order_by("country_code")
            )
            for item in by_country:
                self.stdout.write(
                    f"  - {item['country_code']}: {item['count']} records"
                )
            return

        # Confirmation prompt (unless --force)
        if not force:
            self.stdout.write(
                self.style.WARNING(f"\nYou are about to delete {count} {description}!")
            )
            # Show breakdown by country
            by_country = (
                queryset.values("country_code")
                .annotate(
                    count=__import__("django.db.models", fromlist=["Count"]).Count("id")
                )
                .order_by("country_code")
            )
            for item in by_country:
                self.stdout.write(
                    f"  - {item['country_code']}: {item['count']} records"
                )

            confirm = input("\nAre you sure you want to proceed? [y/N]: ")
            if confirm.lower() != "y":
                self.stdout.write(self.style.WARNING("Deletion cancelled."))
                return

        # Perform deletion
        deleted_count, _ = queryset.delete()
        self.stdout.write(
            self.style.SUCCESS(f"Successfully deleted {deleted_count} {description}")
        )

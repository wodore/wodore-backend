from django.core.management.base import BaseCommand
from django.db import transaction

from server.apps.meteo.models import WeatherCode


class Command(BaseCommand):
    help = "Reset weather data by deleting all WeatherCode entries and optionally related symbols"

    def add_arguments(self, parser):
        parser.add_argument(
            "--icons",
            action="store_true",
            help="Also delete weather-related symbols (use with caution)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be deleted without making changes",
        )
        parser.add_argument(
            "--org",
            type=str,
            help="Only delete weather codes from specific organization (slug)",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        dry_run = options.get("dry_run", False)
        delete_icons = options.get("icons", False)
        org_slug = options.get("org")

        if dry_run:
            self.stdout.write(
                self.style.WARNING("DRY RUN MODE - No changes will be made\n")
            )

        # Count weather codes
        qs = WeatherCode.objects.all()
        if org_slug:
            qs = qs.filter(source_organization__slug=org_slug)
            self.stdout.write(f"Filtering by organization: {org_slug}")

        total_codes = qs.count()

        if total_codes == 0:
            self.stdout.write(self.style.SUCCESS("No weather codes to delete"))
            return

        # Show breakdown by organization
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("Weather Codes to Delete:")
        self.stdout.write("=" * 60)

        orgs = qs.values_list("source_organization__slug", flat=True).distinct()
        for org in orgs:
            count = qs.filter(source_organization__slug=org).count()
            self.stdout.write(f"  {org}: {count} codes")

        self.stdout.write(f"\nTotal: {total_codes} codes")

        # Delete icons if requested
        if delete_icons:
            # Get unique symbols used by these weather codes
            from server.apps.symbols.models import Symbol

            symbol_day_ids = (
                qs.filter(symbol_day__isnull=False)
                .values_list("symbol_day", flat=True)
                .distinct()
            )
            symbol_night_ids = (
                qs.filter(symbol_night__isnull=False)
                .values_list("symbol_night", flat=True)
                .distinct()
            )
            all_symbol_ids = set(symbol_day_ids) | set(symbol_night_ids)

            symbols_qs = Symbol.objects.filter(id__in=all_symbol_ids)
            symbols_count = symbols_qs.count()

            if symbols_count > 0:
                self.stdout.write("\n" + "=" * 60)
                self.stdout.write("Symbols to Delete:")
                self.stdout.write("=" * 60)

                # Show breakdown by style
                for style in ["detailed", "simple", "mono"]:
                    count = symbols_qs.filter(style=style).count()
                    if count > 0:
                        self.stdout.write(f"  {style}: {count} symbols")

                self.stdout.write(f"\nTotal: {symbols_count} symbols")
                self.stdout.write(
                    self.style.WARNING(
                        "\n⚠ WARNING: This will also delete the symbol files!"
                    )
                )

        # Confirm deletion
        if not dry_run:
            self.stdout.write("\n" + "=" * 60)
            confirm = input("Are you sure you want to delete? (yes/no): ")
            if confirm.lower() != "yes":
                self.stdout.write(self.style.WARNING("Deletion cancelled"))
                return

        # Delete weather codes
        if not dry_run:
            deleted_count, _ = qs.delete()
            self.stdout.write(
                self.style.SUCCESS(f"\n✓ Deleted {deleted_count} weather codes")
            )

            # Delete symbols if requested
            if delete_icons and symbols_count > 0:
                deleted_symbols, _ = symbols_qs.delete()
                self.stdout.write(
                    self.style.SUCCESS(f"✓ Deleted {deleted_symbols} symbols")
                )
        else:
            self.stdout.write(f"\n→ Would delete {total_codes} weather codes")
            if delete_icons and symbols_count > 0:
                self.stdout.write(f"→ Would delete {symbols_count} symbols")

        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("Done!")
        self.stdout.write("=" * 60)

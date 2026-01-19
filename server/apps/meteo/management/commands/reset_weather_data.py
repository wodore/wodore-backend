from django.core.management.base import BaseCommand
from django.db import transaction

from server.apps.meteo.models import (
    WeatherCode,
    WeatherCodeSymbol,
    WeatherCodeSymbolCollection,
)


class Command(BaseCommand):
    help = "Reset weather data by deleting WeatherCode entries, collections, and optionally symbols"

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
            "--collection",
            type=str,
            help="Only delete data from specific collection (slug)",
        )
        parser.add_argument(
            "--codes-only",
            action="store_true",
            help="Only delete WeatherCode entries (keep collections and symbols)",
        )
        parser.add_argument(
            "--collections-only",
            action="store_true",
            help="Only delete collections and their mappings (keep WeatherCodes)",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        dry_run = options.get("dry_run", False)
        delete_icons = options.get("icons", False)
        collection_slug = options.get("collection")
        codes_only = options.get("codes_only", False)
        collections_only = options.get("collections_only", False)

        if dry_run:
            self.stdout.write(
                self.style.WARNING("DRY RUN MODE - No changes will be made\n")
            )

        # Delete collections and their mappings
        if not codes_only:
            collections_qs = WeatherCodeSymbolCollection.objects.all()
            if collection_slug:
                collections_qs = collections_qs.filter(slug=collection_slug)
                self.stdout.write(f"Filtering by collection: {collection_slug}")

            collections_count = collections_qs.count()

            if collections_count > 0:
                self.stdout.write("\n" + "=" * 60)
                self.stdout.write("Collections to Delete:")
                self.stdout.write("=" * 60)

                for collection in collections_qs:
                    symbol_count = collection.symbols.count()
                    self.stdout.write(
                        f"  {collection.slug}: {symbol_count} symbol mappings"
                    )

                self.stdout.write(f"\nTotal: {collections_count} collections")

                # Get symbols used by these collections if deleting icons
                if delete_icons:
                    code_symbols_qs = WeatherCodeSymbol.objects.filter(
                        collection__in=collections_qs
                    )

                    symbol_day_ids = (
                        code_symbols_qs.filter(symbol_day__isnull=False)
                        .values_list("symbol_day", flat=True)
                        .distinct()
                    )
                    symbol_night_ids = (
                        code_symbols_qs.filter(symbol_night__isnull=False)
                        .values_list("symbol_night", flat=True)
                        .distinct()
                    )
                    all_symbol_ids = set(symbol_day_ids) | set(symbol_night_ids)

                    from server.apps.symbols.models import Symbol

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

        # Delete weather codes
        if not collections_only:
            codes_qs = WeatherCode.objects.all()
            total_codes = codes_qs.count()

            if total_codes > 0:
                self.stdout.write("\n" + "=" * 60)
                self.stdout.write("Weather Codes to Delete:")
                self.stdout.write("=" * 60)
                self.stdout.write(f"  Total: {total_codes} universal WMO codes")

        # Confirm deletion
        if not dry_run:
            self.stdout.write("\n" + "=" * 60)
            confirm = input("Are you sure you want to delete? (yes/no): ")
            if confirm.lower() != "yes":
                self.stdout.write(self.style.WARNING("Deletion cancelled"))
                return

        # Perform deletions
        if not dry_run:
            # Delete collections (this cascades to WeatherCodeSymbol)
            if not codes_only and collections_count > 0:
                deleted_collections, details = collections_qs.delete()
                self.stdout.write(
                    self.style.SUCCESS(f"\n✓ Deleted {deleted_collections} collections")
                )
                # Show cascade deletions
                if "meteo.WeatherCodeSymbol" in details:
                    self.stdout.write(
                        f"  └─ Cascaded {details['meteo.WeatherCodeSymbol']} symbol mappings"
                    )

            # Delete symbols if requested
            if delete_icons and not codes_only and symbols_count > 0:
                deleted_symbols, _ = symbols_qs.delete()
                self.stdout.write(
                    self.style.SUCCESS(f"✓ Deleted {deleted_symbols} symbols")
                )

            # Delete weather codes
            if not collections_only and total_codes > 0:
                deleted_codes, _ = codes_qs.delete()
                self.stdout.write(
                    self.style.SUCCESS(f"✓ Deleted {deleted_codes} weather codes")
                )
        else:
            if not codes_only and collections_count > 0:
                self.stdout.write(f"\n→ Would delete {collections_count} collections")
            if delete_icons and not codes_only and symbols_count > 0:
                self.stdout.write(f"→ Would delete {symbols_count} symbols")
            if not collections_only and total_codes > 0:
                self.stdout.write(f"→ Would delete {total_codes} weather codes")

        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("Done!")
        self.stdout.write("=" * 60)

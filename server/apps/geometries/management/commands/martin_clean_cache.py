from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "Clean up Martin tile cache entries from the database"

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=7,
            help="Delete cache entries older than this many days (default: 7). Use 0 to delete ALL cache entries.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be deleted without actually deleting",
        )

    def handle(self, *args, **options):
        days = options["days"]
        dry_run = options["dry_run"]

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"DRY RUN - Would delete cache entries older than {days} days"
                )
            )
        else:
            self.stdout.write(f"Deleting cache entries older than {days} days...")

        with connection.cursor() as cursor:
            if days == 0:
                # Count all entries
                cursor.execute("SELECT COUNT(*) FROM geometries_tile_cache")
                count = cursor.fetchone()[0]

                if dry_run:
                    self.stdout.write(f"Would delete {count} cache entries (ALL)")
                else:
                    cursor.execute("DELETE FROM geometries_tile_cache")
                    self.stdout.write(
                        self.style.SUCCESS(f"Deleted {count} cache entries (ALL)")
                    )
            else:
                # Count entries to be deleted
                cursor.execute(
                    "SELECT COUNT(*) FROM geometries_tile_cache WHERE expires_at < NOW() - (%s || ' days')::interval",
                    [days],
                )
                count = cursor.fetchone()[0]

                if dry_run:
                    self.stdout.write(
                        f"Would delete {count} cache entries older than {days} days"
                    )
                else:
                    # Use the cleanup function
                    cursor.execute("SELECT cleanup_tile_cache(%s)", [days])
                    deleted = cursor.fetchone()[0]
                    self.stdout.write(
                        self.style.SUCCESS(f"Deleted {deleted} cache entries")
                    )

        # Show cache statistics
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM geometries_tile_cache")
            total = cursor.fetchone()[0]

            cursor.execute(
                "SELECT pg_size_pretty(pg_total_relation_size(%s))",
                ["geometries_tile_cache"],
            )
            size = cursor.fetchone()[0]

            self.stdout.write(f"Remaining cache entries: {total}")
            self.stdout.write(f"Total cache size: {size}")

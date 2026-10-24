"""Phase E gate artifact for the geoplace-availability change.

Lists huts that have availability data but no place association (design
D5). Phase E (hut model removal) is gated on this report being empty.
"""

from django.core.management.base import BaseCommand
from django.db.models import Count

from ...place_link import unmatched_huts


class Command(BaseCommand):
    help = (
        "List huts with availability data but no geoplace association "
        "(geoplace-availability Phase E gate)"
    )

    def handle(self, *args, **options):
        huts = unmatched_huts().annotate(rows=Count("availabilities"))
        if not huts:
            self.stdout.write(
                self.style.SUCCESS(
                    "All huts with availability data resolve to places "
                    "(Phase E gate: OK)"
                )
            )
            return
        self.stdout.write(
            self.style.WARNING(
                f"{len(huts)} hut(s) with availability but no place association "
                "(Phase E gate: NOT empty):"
            )
        )
        for hut in huts:
            last = hut.availabilities.order_by("-availability_date").first()
            last_info = f", last date {last.availability_date}" if last else ""
            self.stdout.write(f"  {hut.slug}: {hut.rows} row(s){last_info}")

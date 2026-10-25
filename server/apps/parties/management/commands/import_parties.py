"""Merge owners.Owner rows into parties.Party (OpenSpec geoplace-parties 3.1).

Idempotent sync — Owner rows keep arriving from hut imports until the
huts app retires, so a re-runnable command beats a one-shot data
migration (design decision 5).
"""

from typing import Any, override

from django_admin_runner import register_command

from django.core.management.base import BaseCommand, CommandParser

from server.apps.owners.models import Owner
from server.apps.parties.models import Party
from server.apps.parties.services import merge_owner


@register_command(group="Parties")
class Command(BaseCommand):
    help = "Merge owners.Owner rows into parties.Party (idempotent)"

    @override
    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be merged without writing",
        )

    @override
    def handle(self, *args: Any, **options: Any) -> None:
        dry_run = options["dry_run"]
        owners = Owner.objects.all().order_by("slug")

        total = owners.count()
        self.stdout.write(
            f"Merging {total} owners into parties{' (dry run)' if dry_run else ''}..."
        )

        created = existing = linked = 0
        for owner in owners.iterator(chunk_size=500):
            if dry_run:
                if Party.objects.filter(
                    dedup_key=Party.normalize_key(owner.slug)
                ).exists():
                    existing += 1
                else:
                    created += 1
                    self.stdout.write(f"  [DRY RUN] would create: {owner.slug}")
                continue

            _party, party_created, link_created = merge_owner(owner)
            if party_created:
                created += 1
            else:
                existing += 1
            if link_created:
                linked += 1

        if dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    f"[DRY RUN] {total} owners: {created} would become parties, "
                    f"{existing} already merged"
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Merged {total} owners: {created} parties created "
                    f"({existing} already existed), {linked} links added"
                )
            )

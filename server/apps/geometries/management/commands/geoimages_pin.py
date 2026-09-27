"""Sync (pin) external provider images for huts and geoplaces.

Background/bulk counterpart of the endpoints' lazy pin-on-first-visit.
Schedulable as a recurring django-q2 task via the Schedule admin
(django-admin-runner command registry, group "Geometries") — e.g. a
monthly hygiene sweep for rarely visited places.

Examples:
    manage.py geoimages_pin --place=laemmeren              # one hut
    manage.py geoimages_pin --place=test-peak-dammastock --type=geoplace
    manage.py geoimages_pin --all                          # sweep
    manage.py geoimages_pin --all --dry-run
    manage.py geoimages_pin --place=laemmeren --check-origins
"""

from django_admin_runner import register_command

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from server.apps.geometries.pinning import (
    GeoPlaceImageAssociation,
    sync_place_images,
)

HELP_TYPE = "Which place type to sync: hut, geoplace or all (default)."


def _sweep_targets():
    """Every public hut plus every geoplace that already has pins."""
    from server.apps.geometries.models import GeoPlace
    from server.apps.huts.models import Hut

    huts = Hut.objects.filter(is_active=True, is_public=True).iterator()
    pinned_geoplace_ids = GeoPlaceImageAssociation.objects.values_list(
        "geo_place_id", flat=True
    ).distinct()
    geoplaces = GeoPlace.objects.filter(
        Q(id__in=pinned_geoplace_ids), is_active=True, is_public=True
    ).iterator()
    yield from (("hut", hut) for hut in huts)
    yield from (("geoplace", place) for place in geoplaces)


@register_command(group="Geometries")
class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument(
            "--place", metavar="SLUG", help="Sync a single place by slug."
        )
        parser.add_argument(
            "--type", choices=("hut", "geoplace", "all"), default="all", help=HELP_TYPE
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Sync every public hut and every geoplace that already has pins.",
        )
        parser.add_argument(
            "--dry-run", action="store_true", help="Report only, do not write."
        )
        parser.add_argument(
            "--check-origins",
            action="store_true",
            help=(
                "HEAD-check pins missing from fresh results; dead origins "
                "(404/410) move to review instead of being deleted."
            ),
        )

    def handle(self, *args, **options):
        if not options["place"] and not options["all"]:
            raise CommandError("Nothing to do: pass --place=<slug> or --all.")
        check_origins = bool(options["check_origins"])
        dry_run = bool(options["dry_run"])

        if options["place"]:
            targets = self._single_place(options["place"], options["type"])
        else:
            targets = _sweep_targets()

        synced = failed = 0
        for place_type, place in targets:
            pins = getattr(place, "image_associations", None)
            pin_count = (
                pins.count() if place_type == "geoplace" else place.image_set.count()
            )
            label = f"{place_type}:{place.slug} (pins: {pin_count})"
            if dry_run:
                self.stdout.write(f"[dry-run] would sync {label}")
                continue
            try:
                stats = sync_place_images(place, check_origins=check_origins)
            except Exception as e:
                failed += 1
                self.stdout.write(self.style.ERROR(f"sync failed {label}: {e}"))
                continue
            synced += 1
            self.stdout.write(f"synced {label}: {stats}")
        if not dry_run:
            self.stdout.write(
                self.style.SUCCESS(f"Done: {synced} synced, {failed} failed.")
            )

    def _single_place(self, slug: str, place_type: str):
        from server.apps.geometries.models import GeoPlace
        from server.apps.huts.models import Hut

        found = []
        types = ("hut", "geoplace") if place_type == "all" else (place_type,)
        for ptype in types:
            model = Hut if ptype == "hut" else GeoPlace
            place = model.objects.filter(
                slug=slug, is_active=True, is_public=True
            ).first()
            if place:
                found.append((ptype, place))
        if not found:
            raise CommandError(f"No active public place '{slug}' of type(s) {types}.")
        return found

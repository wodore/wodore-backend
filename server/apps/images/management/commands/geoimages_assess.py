"""Assess pinned images: perceptual hash, quality score, thumbhash, duplicates.

Runs on pixels from our own imagor only (cached thumbnails); pure
Pillow/numpy — no models, no external services. Results land on the
Image rows (columns + image_meta breakdown) and are served through the
image endpoints (properties.thumbhash / properties.extra).

Schedulable via the Schedule admin (django-admin-runner, group
"Images"); usually combined with geoimages_pin --assess.

Examples:
    manage.py geoimages_assess --place=laemmeren
    manage.py geoimages_assess --all --dry-run
    manage.py geoimages_assess --all --force-recompute
"""

from django_admin_runner import register_command

from django.core.management.base import BaseCommand, CommandError

from server.apps.geometries.pinning import GeoPlaceImageAssociation
from server.apps.images.assessment import assess_place_pins


def _sweep_targets():
    """Places that have pins (huts and geoplaces)."""
    from server.apps.geometries.models import GeoPlace
    from server.apps.huts.models import Hut, HutImageAssociation

    hut_ids = HutImageAssociation.objects.values_list("hut_id", flat=True).distinct()
    geoplace_ids = GeoPlaceImageAssociation.objects.values_list(
        "geo_place_id", flat=True
    ).distinct()
    yield from (
        ("hut", hut)
        for hut in Hut.objects.filter(
            id__in=hut_ids, is_active=True, is_public=True
        ).iterator()
    )
    yield from (
        ("geoplace", place)
        for place in GeoPlace.objects.filter(
            id__in=geoplace_ids, is_active=True, is_public=True
        ).iterator()
    )


@register_command(group="Images")
class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument(
            "--place", metavar="SLUG", help="Assess a single place by slug."
        )
        parser.add_argument(
            "--type",
            choices=("hut", "geoplace", "all"),
            default="all",
            help="Which place type: hut, geoplace or all (default).",
        )
        parser.add_argument(
            "--all", action="store_true", help="Assess every place that has pins."
        )
        parser.add_argument(
            "--dry-run", action="store_true", help="Report only, do not write."
        )
        parser.add_argument(
            "--force-recompute",
            action="store_true",
            help="Re-assess images that already carry phash/quality/thumbhash.",
        )

    def handle(self, *args, **options):
        if not options["place"] and not options["all"]:
            raise CommandError("Nothing to do: pass --place=<slug> or --all.")
        force = bool(options["force_recompute"])
        dry_run = bool(options["dry_run"])

        if options["place"]:
            targets = self._single_place(options["place"], options["type"])
        else:
            targets = _sweep_targets()

        assessed_places = failed = 0
        for place_type, place in targets:
            label = f"{place_type}:{place.slug}"
            if dry_run:
                self.stdout.write(f"[dry-run] would assess {label}")
                continue
            try:
                stats = assess_place_pins(place, force=force)
            except Exception as e:
                failed += 1
                self.stdout.write(self.style.ERROR(f"assess failed {label}: {e}"))
                continue
            assessed_places += 1
            self.stdout.write(f"assessed {label}: {stats}")
        if not dry_run:
            self.stdout.write(
                self.style.SUCCESS(f"Done: {assessed_places} places, {failed} failed.")
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

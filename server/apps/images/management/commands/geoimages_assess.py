"""Assess pinned images: perceptual hash, quality score, thumbhash, duplicates.

Runs on pixels from our own imagor only (cached thumbnails); pure
Pillow/numpy — no models, no external services. Results land on the
Image rows (columns + image_meta breakdown) and are served through the
image endpoints (properties.thumbhash / properties.extra).

Schedulable via the Schedule admin (django-admin-runner, group
"Images"); usually combined with geoimages_pin --assess.

By default every place that has pins is assessed; already-assessed
images are skipped unless ``--force-recompute``.

Examples:
    manage.py geoimages_assess                      # all pinned places
    manage.py geoimages_assess --place=laemmeren
    manage.py geoimages_assess --dry-run
    manage.py geoimages_assess --force-recompute
    manage.py geoimages_assess --bbox=7.5,46.0,8.5,46.8
    manage.py geoimages_assess --type=hut --no-progress
"""

from django_admin_runner import register_command
from django_admin_runner.forms import _hidden_aware_argparse

from django.core.management.base import BaseCommand, CommandError

from server.apps.geometries.bbox import parse_bbox
from server.apps.geometries.pinning import GeoPlaceImageAssociation
from server.apps.geometries.sweep import run_sweep
from server.apps.geometries.widgets import BBoxWidget
from server.apps.images.assessment import assess_place_pins


def _sweep_targets(place_type: str, bbox=None):
    """Materialized targets: every place that has pins.

    Filtered by place type and (optionally) a WGS84 bbox polygon. No
    server-side cursor spans the per-place loop.
    """
    from server.apps.geometries.models import GeoPlace
    from server.apps.huts.models import Hut, HutImageAssociation

    huts = Hut.objects.filter(
        id__in=HutImageAssociation.objects.values_list("hut_id", flat=True).distinct(),
        is_active=True,
        is_public=True,
    )
    geoplaces = GeoPlace.objects.filter(
        id__in=GeoPlaceImageAssociation.objects.values_list(
            "geo_place_id", flat=True
        ).distinct(),
        is_active=True,
        is_public=True,
    )
    if bbox is not None:
        huts = huts.filter(location__intersects=bbox)
        geoplaces = geoplaces.filter(location__intersects=bbox)

    targets: list[tuple[str, Hut | GeoPlace]] = []
    if place_type in ("hut", "all"):
        targets += [("hut", hut) for hut in huts]
    if place_type in ("geoplace", "all"):
        targets += [("geoplace", place) for place in geoplaces]
    return targets


@register_command(group="Images")
class Command(BaseCommand):
    help = __doc__ or ""

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
            "--all",
            action="store_true",
            help=(
                "Explicit full sweep. Kept for compatibility: the default "
                "already assesses every place that has pins."
            ),
        )
        with _hidden_aware_argparse():
            parser.add_argument(
                "--bbox",
                metavar="LON_MIN,LAT_MIN,LON_MAX,LAT_MAX",
                widget=BBoxWidget(),
                help=(
                    "Restrict the sweep to this bounding box (WGS84 degrees). "
                    "In the admin form, draw the rectangle on the map."
                ),
            )
        parser.add_argument(
            "--dry-run", action="store_true", help="Report only, do not write."
        )
        parser.add_argument(
            "--force-recompute",
            action="store_true",
            help="Re-assess images that already carry phash/quality/thumbhash.",
        )
        parser.add_argument(
            "--no-progress",
            action="store_true",
            help="Disable the progress bar and print results as they complete "
            "(useful for cron jobs).",
        )

    def handle(self, *args, **options):
        force = bool(options["force_recompute"])
        dry_run = bool(options["dry_run"])
        no_progress = bool(options["no_progress"])
        bbox_polygon = None
        if options["bbox"]:
            try:
                bbox_polygon = parse_bbox(options["bbox"])
            except ValueError as e:
                raise CommandError(f"--bbox: {e}") from e

        if options["place"]:
            targets = self._single_place(options["place"], options["type"])
            mode = f"place {options['place']!r}"
        else:
            targets = _sweep_targets(options["type"], bbox=bbox_polygon)
            mode = "all pinned places"
            if bbox_polygon is not None:
                mode += " + bbox"
        if not targets:
            self.stdout.write(f"Nothing to do ({mode}): no matching places.")
            return

        if dry_run:
            for place_type, place in targets[:10]:
                self.stdout.write(f"[dry-run] would assess {place_type}:{place.slug}")
            if len(targets) > 10:
                self.stdout.write(f"[dry-run] … and {len(targets) - 10} more.")
            self.stdout.write(
                self.style.SUCCESS(f"Dry run: {len(targets)} place(s) ({mode}).")
            )
            return

        def work(place_type, place, report) -> bool:
            label = f"{place_type}:{place.slug}"
            try:
                stats = assess_place_pins(place, force=force)
            except Exception as e:
                report(f"assess failed {label}: {e}", False)
                return False
            report(f"assessed {label}: {stats}", True)
            return True

        assessed_places, failed = run_sweep(
            targets,
            mode=mode,
            verb="Assessing pinned images",
            no_progress=no_progress,
            stdout=self.stdout,
            stderr=self.stderr,
            work=work,
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Done: {assessed_places} places, {failed} failed ({mode})."
            )
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

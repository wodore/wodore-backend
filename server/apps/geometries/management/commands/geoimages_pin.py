"""Sync (pin) external provider images for huts and geoplaces.

Background/bulk counterpart of the endpoints' lazy pin-on-first-visit.
Schedulable as a recurring django-q2 task via the Schedule admin
(django-admin-runner command registry, group "Geometries") — e.g. a
monthly hygiene sweep for rarely visited places.

Examples:
    manage.py geoimages_pin                     # places without pins yet (default)
    manage.py geoimages_pin --all               # full sweep
    manage.py geoimages_pin --place=laemmeren   # one hut
    manage.py geoimages_pin --place=test-peak-dammastock --type=geoplace
    manage.py geoimages_pin --all --dry-run
    manage.py geoimages_pin --place=laemmeren --check-origins
    manage.py geoimages_pin --all --budget=60   # wait longer per place
    manage.py geoimages_pin --all --no-progress # plain output (cron jobs)
"""

from django_admin_runner import register_command
from django_admin_runner.forms import _hidden_aware_argparse

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from server.apps.geometries.bbox import parse_bbox
from server.apps.geometries.pinning import (
    GeoPlaceImageAssociation,
    sync_place_images,
    warmup_place_image_cache,
)
from server.apps.geometries.sweep import run_sweep
from server.apps.geometries.widgets import BBoxWidget

HELP_TYPE = "Which place type to sync: hut, geoplace or all (default)."


def _sweep_targets(
    all_places: bool, place_type: str, bbox=None, limit: int | None = None
):
    """Materialized sweep targets.

    Default (``all_places=False``): only places never synced from
    providers (``images_pinned_at`` is null) — the incremental "pin what
    is missing" mode. ``--all`` sweeps every public hut and every
    geoplace that already has pins (geoplaces are provider-fan-out heavy,
    so a full sweep re-sweeps only known ones).

    Targets are materialized into a list: no server-side cursor spans the
    (hours-long) per-place loop. Unpinned geoplaces number in the hundreds
    of thousands, so they are capped by *limit* (huts first, geoplaces
    fill the remaining budget) — pass ``--type=geoplace`` to fill the
    whole budget with geoplaces instead.
    """
    from server.apps.geometries.models import GeoPlace
    from server.apps.huts.models import Hut

    huts = Hut.objects.filter(is_active=True, is_public=True)
    geoplaces = GeoPlace.objects.filter(is_active=True, is_public=True).defer("shape")
    if all_places:
        pinned_geoplace_ids = GeoPlaceImageAssociation.objects.values_list(
            "geo_place_id", flat=True
        ).distinct()
        geoplaces = geoplaces.filter(Q(id__in=pinned_geoplace_ids))
    else:
        huts = huts.filter(images_pinned_at__isnull=True)
        geoplaces = geoplaces.filter(images_pinned_at__isnull=True).order_by("id")

    targets: list[tuple[str, Hut | GeoPlace]] = []
    if place_type in ("hut", "all"):
        if bbox is not None:
            huts = huts.filter(location__intersects=bbox)
        targets += [("hut", hut) for hut in huts]
    if place_type in ("geoplace", "all"):
        if bbox is not None:
            geoplaces = geoplaces.filter(location__intersects=bbox)
        if not all_places and limit is not None:
            geoplaces = geoplaces[: max(0, limit - len(targets))]
        targets += [("geoplace", place) for place in geoplaces]
    return targets


@register_command(group="Geometries")
class Command(BaseCommand):
    help = __doc__ or ""

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
            help=(
                "Full sweep: every public hut and every geoplace that already "
                "has pins. Default: only places never synced from providers "
                "(images_pinned_at is null)."
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
            "--limit",
            type=int,
            default=200,
            metavar="N",
            help=(
                "Cap on places per run in the default (unpinned) mode — huts "
                "first, geoplaces fill the remaining budget (default 200; the "
                "unpinned geoplace table is huge). --all ignores it."
            ),
        )
        parser.add_argument(
            "--no-progress",
            action="store_true",
            help="Disable the progress bar and print results as they complete "
            "(useful for cron jobs).",
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
        parser.add_argument(
            "--warmup-image-cache",
            action="store_true",
            help=(
                "After syncing, pre-fetch the imagor variant URLs (preview/medium) "
                "for each place's pins — the sync itself stays metadata-only; "
                "this makes the first visitor's render instant."
            ),
        )
        parser.add_argument(
            "--assess",
            action="store_true",
            help=(
                "After syncing, run quality assessment (phash, quality score, "
                "thumbhash, duplicate detection) on the place's pins."
            ),
        )
        parser.add_argument(
            "--budget",
            type=float,
            default=None,
            metavar="SECONDS",
            help=(
                "Overall wall-clock budget per place's provider fan-out, in "
                "seconds; 0 or negative disables it (wait for all providers). "
                "Default: 3× the IMAGES_FANOUT_BUDGET_SECONDS setting (30s "
                "at the 10s request-path default) — background sweeps can "
                "afford to wait longer for completeness."
            ),
        )

    def handle(self, *args, **options):
        check_origins = bool(options["check_origins"])
        warmup = bool(options["warmup_image_cache"])
        assess = bool(options["assess"])
        dry_run = bool(options["dry_run"])
        budget = options["budget"]
        if budget is None:
            # Background sweeps can afford to wait longer than the request
            # path: triple the env-backed fan-out budget unless --budget is
            # passed explicitly (0/negative still disables the budget).
            from server.apps.geometries.providers.base import fanout_budget_seconds

            budget = fanout_budget_seconds() * 3
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
            targets = _sweep_targets(
                options["all"],
                options["type"],
                bbox=bbox_polygon,
                limit=options["limit"],
            )
            mode = "full sweep" if options["all"] else "unpinned only"
            if bbox_polygon is not None:
                mode += " + bbox"
        if not targets:
            self.stdout.write(f"Nothing to do ({mode}): no matching places.")
            return

        if dry_run:
            for place_type, place in targets[:10]:
                pins = getattr(place, "image_associations", None)
                pin_count = (
                    pins.count()
                    if place_type == "geoplace" and pins is not None
                    else place.image_set.count()
                )
                self.stdout.write(
                    f"[dry-run] would sync {place_type}:{place.slug} (pins: {pin_count})"
                )
            if len(targets) > 10:
                self.stdout.write(f"[dry-run] … and {len(targets) - 10} more.")
            self.stdout.write(
                self.style.SUCCESS(f"Dry run: {len(targets)} place(s) ({mode}).")
            )
            return

        def work(place_type, place, report) -> bool:
            pins = getattr(place, "image_associations", None)
            pin_count = (
                pins.count()
                if place_type == "geoplace" and pins is not None
                else place.image_set.count()
            )
            label = f"{place_type}:{place.slug} (pins: {pin_count})"
            try:
                stats = sync_place_images(
                    place, check_origins=check_origins, budget=budget
                )
            except Exception as e:
                report(f"sync failed {label}: {e}", False)
                return False
            report(f"synced {label}: {stats}", True)

            def has_pins() -> bool:
                # Re-checked after the sync: the place may have gained pins.
                if place_type == "geoplace" and pins is not None:
                    return pins.exists()
                return place.image_set.exists()

            if assess and has_pins():
                from server.apps.images.assessment import assess_place_pins

                assess_stats = assess_place_pins(place)
                report(f"  assessed pins for {label}: {assess_stats}", True)
            if warmup and has_pins():
                warmed = warmup_place_image_cache(place)
                report(f"  warmed {warmed} imagor variants for {label}", True)
            return True

        synced, failed = run_sweep(
            targets,
            mode=mode,
            verb="Pinning images",
            no_progress=no_progress,
            stdout=self.stdout,
            stderr=self.stderr,
            work=work,
        )
        self.stdout.write(
            self.style.SUCCESS(f"Done: {synced} synced, {failed} failed ({mode}).")
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

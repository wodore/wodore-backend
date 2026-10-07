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
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from server.apps.geometries.pinning import (
    GeoPlaceImageAssociation,
    sync_place_images,
    warmup_place_image_cache,
)

HELP_TYPE = "Which place type to sync: hut, geoplace or all (default)."


def _sweep_targets(all_places: bool, place_type: str):
    """Materialized sweep targets.

    Default (``all_places=False``): only places never synced from
    providers (``images_pinned_at`` is null) — the incremental "pin what
    is missing" mode. ``--all`` sweeps every public hut and every
    geoplace that already has pins (geoplaces are provider-fan-out heavy,
    so a full sweep re-sweeps only known ones).

    Targets are materialized into a list: no server-side cursor spans the
    (hours-long) per-place loop.
    """
    from server.apps.geometries.models import GeoPlace
    from server.apps.huts.models import Hut

    huts = Hut.objects.filter(is_active=True, is_public=True)
    geoplaces = GeoPlace.objects.filter(is_active=True, is_public=True)
    if all_places:
        pinned_geoplace_ids = GeoPlaceImageAssociation.objects.values_list(
            "geo_place_id", flat=True
        ).distinct()
        geoplaces = geoplaces.filter(Q(id__in=pinned_geoplace_ids))
    else:
        huts = huts.filter(images_pinned_at__isnull=True)
        geoplaces = geoplaces.filter(images_pinned_at__isnull=True)

    targets: list[tuple[str, Hut | GeoPlace]] = []
    if place_type in ("hut", "all"):
        targets += [("hut", hut) for hut in huts]
    if place_type in ("geoplace", "all"):
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
                "Default: the IMAGES_FANOUT_BUDGET_SECONDS setting (10s), "
                "which trades completeness for latency on the request path — "
                "background sweeps can afford to wait longer."
            ),
        )

    def handle(self, *args, **options):
        check_origins = bool(options["check_origins"])
        warmup = bool(options["warmup_image_cache"])
        assess = bool(options["assess"])
        dry_run = bool(options["dry_run"])
        budget = options["budget"]
        no_progress = bool(options["no_progress"])

        if options["place"]:
            targets = self._single_place(options["place"], options["type"])
            mode = f"place {options['place']!r}"
        else:
            targets = _sweep_targets(options["all"], options["type"])
            mode = "full sweep" if options["all"] else "unpinned only"
        if not targets:
            self.stdout.write(f"Nothing to do ({mode}): no matching places.")
            return

        if dry_run:
            for place_type, place in targets:
                pins = getattr(place, "image_associations", None)
                pin_count = (
                    pins.count()
                    if place_type == "geoplace" and pins is not None
                    else place.image_set.count()
                )
                self.stdout.write(
                    f"[dry-run] would sync {place_type}:{place.slug} (pins: {pin_count})"
                )
            self.stdout.write(
                self.style.SUCCESS(f"Dry run: {len(targets)} place(s) ({mode}).")
            )
            return

        synced = failed = 0

        def report(message: str, progress: Progress) -> None:
            # Bare print()s land inside the live area; progress.console.print
            # renders them above the bar instead (and prints plainly when the
            # progress display is disabled).
            progress.console.print(message)

        progress = Progress(
            SpinnerColumn(finished_text="✓"),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TextColumn("•"),
            TimeElapsedColumn(),
            TextColumn("{task.fields[status]}"),
            disable=no_progress,
        )
        with progress:
            task = progress.add_task(
                f"[cyan]Pinning images ({mode})...",
                total=len(targets),
                status="[dim]starting...",
            )
            for place_type, place in targets:
                progress.update(task, status=f"[cyan]{place_type}:{place.slug}")
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
                    failed += 1
                    report(self.style.ERROR(f"sync failed {label}: {e}"), progress)
                else:
                    synced += 1
                    report(f"synced {label}: {stats}", progress)
                    if assess:
                        from server.apps.images.assessment import assess_place_pins

                        assess_stats = assess_place_pins(place)
                        report(f"  assessed pins for {label}: {assess_stats}", progress)
                    if warmup:
                        warmed = warmup_place_image_cache(place)
                        report(
                            f"  warmed {warmed} imagor variants for {label}", progress
                        )
                progress.advance(task)
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

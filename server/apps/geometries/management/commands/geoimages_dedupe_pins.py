"""Delete duplicated pinned images (prefix-stacked source_idents).

Legacy bug: ``WodoreProvider`` passes existing pins back through the pinning
pipeline (provider = source_org slug, source_id = the row's source_ident), and
``pin_place_images`` re-pinned them under a provider prefix stacked onto the
ident ("camptocamp:camptocamp:...") — every live fetch + pin cycle duplicated
every visible pin of a place. Fixed in the same release; this command removes
the historical duplicates.

A duplicate is any ``Image`` whose ``source_ident`` starts with the same
organization slug twice (``^([a-z0-9_-]+):\\1:``). The original pin (single
prefix) is kept. Response caches of every affected place are invalidated so
the next visitor sees the cleaned gallery.

Examples:
    manage.py geoimages_dedupe_pins                # dry run, report only
    manage.py geoimages_dedupe_pins --apply        # delete duplicates
    manage.py geoimages_dedupe_pins --place=laemmeren --apply
    manage.py geoimages_dedupe_pins --bbox=7.5,46.0,8.5,46.8 --apply
"""

import re
from typing import Any, override

from django_admin_runner import register_command
from django_admin_runner.forms import _hidden_aware_argparse

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db.models import Q

from server.apps.geometries.widgets import BBoxWidget

#: A duplicated ident: the organization slug repeated at the start
#: ("camptocamp:camptocamp:waypoint_x", "wikicommons:wikicommons:File:y", …).
DUPLICATE_PATTERN = re.compile(r"^([a-z0-9_-]+):\1:")


@register_command(group="Geometries")
class Command(BaseCommand):
    help = __doc__ or ""

    @override
    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--place",
            metavar="SLUG",
            help="Restrict to one place (hut or geoplace) by slug.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually delete the duplicate images (default: report only).",
        )
        with _hidden_aware_argparse():
            parser.add_argument(
                "--bbox",
                metavar="LON_MIN,LAT_MIN,LON_MAX,LAT_MAX",
                widget=BBoxWidget(),
                help="Restrict to places inside this bounding box (WGS84 degrees).",
            )

    @override
    def handle(self, *args: Any, **options: Any) -> None:
        from server.apps.geometries.bbox import parse_bbox
        from server.apps.geometries.image_response_cache import (
            invalidate_for_hut,
            invalidate_for_place,
        )
        from server.apps.geometries.models import GeoPlaceImageAssociation
        from server.apps.huts.models import HutImageAssociation
        from server.apps.images.models import Image

        bbox_polygon = None
        if options["bbox"]:
            try:
                bbox_polygon = parse_bbox(options["bbox"])
            except ValueError as e:
                raise CommandError(f"--bbox: {e}") from e

        place_filter = Q()
        if options["place"]:
            place_filter &= Q(huts__slug=options["place"]) | Q(
                geo_places__slug=options["place"]
            )
        if bbox_polygon is not None:
            place_filter &= Q(huts__location__intersects=bbox_polygon) | Q(
                geo_places__location__intersects=bbox_polygon
            )

        duplicates = list(
            Image.objects.filter(place_filter, source_ident__isnull=False)
            .filter(source_ident__regex=DUPLICATE_PATTERN.pattern)
            .distinct()
            .select_related("source_org")
        )
        if not duplicates:
            self.stdout.write("No duplicated pins found.")
            return

        duplicate_ids = [image.pk for image in duplicates]

        # Place links via the association models (the reverse M2M accessors on
        # Image are dynamic and invisible to the type checker).
        hut_links = HutImageAssociation.objects.filter(
            image_id__in=duplicate_ids
        ).values_list("image_id", "hut__slug")
        place_links = GeoPlaceImageAssociation.objects.filter(
            image_id__in=duplicate_ids
        ).values_list("image_id", "geo_place__slug")
        huts_by_image: dict[object, list[str]] = {}
        for image_id, slug in hut_links:
            huts_by_image.setdefault(image_id, []).append(slug)
        places_by_image: dict[object, list[str]] = {}
        for image_id, slug in place_links:
            places_by_image.setdefault(image_id, []).append(slug)

        self.stdout.write(f"Found {len(duplicates)} duplicated image(s):")
        for image in duplicates:
            huts = ", ".join(huts_by_image.get(image.pk, [])[:5])
            places = ", ".join(places_by_image.get(image.pk, [])[:5])
            self.stdout.write(
                f"  {image.source_ident}  (huts: {huts or '—'}; places: {places or '—'})"
            )

        if not options["apply"]:
            self.stdout.write(
                self.style.WARNING(
                    f"Dry run: {len(duplicates)} duplicate(s) would be deleted. Use --apply."
                )
            )
            return

        # Collect affected places BEFORE deleting (for cache invalidation).
        hut_slugs = {slug for _img, slug in hut_links}
        place_slugs = {slug for _img, slug in place_links}

        hut_assoc_count = (
            HutImageAssociation.objects.filter(image_id__in=duplicate_ids)
            .delete()[1]
            .get("huts.HutImageAssociation", 0)
        )
        place_assoc_count = (
            GeoPlaceImageAssociation.objects.filter(image_id__in=duplicate_ids)
            .delete()[1]
            .get("geometries.GeoPlaceImageAssociation", 0)
        )
        deleted_images = (
            Image.objects.filter(pk__in=duplicate_ids)
            .delete()[1]
            .get("images.Image", 0)
        )

        for slug in hut_slugs:
            invalidate_for_hut(slug)
        for slug in place_slugs:
            invalidate_for_place(slug)

        self.stdout.write(
            self.style.SUCCESS(
                f"Deleted {deleted_images} duplicate image(s), "
                f"{hut_assoc_count} hut + {place_assoc_count} place association(s); "
                f"invalidated caches for {len(hut_slugs)} hut(s), {len(place_slugs)} place(s)."
            )
        )

"""Generate semantic place relations post-import (task 3.5).

OpenSpec ``geoplace-kinds-operations-graph`` (advisor-rescoped from an
import hook to a standalone command — same end-state, cheaper):
spatial containment → ``part_of``, proximity below a threshold →
``serves``, with confidence < 1.0 (auto-generated edges are replaced
idempotently; curated confidence-1.0 edges are preserved). Bounded to
configured place types.
"""

from typing import Any, override

from django_admin_runner import register_command

from django.contrib.gis.db.models.functions import Distance
from django.core.management.base import BaseCommand, CommandParser
from django.db import transaction

from server.apps.geometries.models import GeoPlace, GeoPlaceRelation
from server.apps.geometries.models._relation import GENERATED_CONFIDENCE

#: Confidence threshold: edges at or above this are curated, preserved.
CURATED_CONFIDENCE = 1.0


@register_command(group="Geometries", timeout=3600)
class Command(BaseCommand):
    help = "Generate place relations from spatial analysis (part_of, serves)"

    @override
    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--types",
            type=str,
            default="part_of,serves",
            help="Comma-separated relation types to generate",
        )
        parser.add_argument(
            "--serve-radius",
            type=int,
            default=5000,
            help="Proximity radius in meters for serves edges (default 5000)",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Max places to process (testing)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be generated without writing",
        )

    @override
    def handle(self, *args: Any, **options: Any) -> None:
        types = [t.strip() for t in options["types"].split(",")]
        serve_radius = options["serve_radius"]
        limit = options["limit"]
        dry_run = options["dry_run"]

        from server.apps.categories.models import Category

        relations = {
            slug: Category.objects.get(slug=slug, parent__slug="relations")
            for slug in types
            if slug in ("part_of", "serves")
        }

        if "part_of" in relations:
            self._generate_part_of(relations["part_of"], limit, dry_run)
        if "serves" in relations:
            self._generate_serves(relations["serves"], serve_radius, limit, dry_run)

    def _generate_part_of(
        self, relation: Any, limit: int | None, dry_run: bool
    ) -> None:
        """Spatial containment: places inside municipality shapes → part_of."""

        municipalities = GeoPlace.objects.filter(
            shape__isnull=False,
            detail_type="admin",
            is_active=True,
        )
        places = GeoPlace.objects.filter(
            is_active=True,
            detail_type__in=["amenity", "natural"],
        )
        if limit:
            places = places[:limit]

        created = 0
        for place in places.iterator(chunk_size=500):
            if place.location is None:
                continue
            container = municipalities.filter(shape__contains=place.location).first()
            if container is None or container.pk == place.pk:
                continue
            created += self._upsert_edge(place, container, relation, dry_run)
        self.stdout.write(
            f"  part_of: {created} edges {'(dry run)' if dry_run else ''}"
        )

    def _generate_serves(
        self, relation: Any, radius: int, limit: int | None, dry_run: bool
    ) -> None:
        """Proximity: places within radius of a hut/served place → serves."""
        served = GeoPlace.objects.filter(
            is_active=True,
            categories__parent__slug="accommodation",
        ).distinct()
        nearby = GeoPlace.objects.filter(
            is_active=True,
            detail_type="amenity",
        ).exclude(categories__parent__slug="accommodation")
        if limit:
            nearby = nearby[:limit]

        created = 0
        for place in nearby.iterator(chunk_size=500):
            if place.location is None:
                continue
            hut = (
                served.filter(location__distance_lte=(place.location, radius))
                .annotate(distance=Distance("location", place.location))
                .order_by("distance")
                .first()
            )
            if hut is None or hut.pk == place.pk:
                continue
            created += self._upsert_edge(place, hut, relation, dry_run)
        self.stdout.write(f"  serves: {created} edges {'(dry run)' if dry_run else ''}")

    def _upsert_edge(
        self,
        from_place: GeoPlace,
        to_place: GeoPlace,
        relation: Any,
        dry_run: bool,
    ) -> int:
        """Idempotent upsert: replace generated edges, preserve curated."""
        if dry_run:
            return 1
        existing = GeoPlaceRelation.objects.filter(
            from_place=from_place,
            to_place=to_place,
            relation=relation,
        ).first()
        if existing is not None and existing.confidence >= CURATED_CONFIDENCE:
            return 0  # curated edge — preserve
        with transaction.atomic():
            GeoPlaceRelation.objects.update_or_create(
                from_place=from_place,
                to_place=to_place,
                relation=relation,
                defaults={"confidence": GENERATED_CONFIDENCE},
            )
        return 1

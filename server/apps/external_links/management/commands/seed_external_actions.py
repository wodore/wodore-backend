"""Seed the open-in action registry (OpenSpec ``external-actions``).

Additive-only ``get_or_create`` — existing rows are NEVER modified, so
curator edits are structurally safe (the review's H2 fix). Link saves
skip health checks (``skip_health_check=True``): the template links
carry ``template_vars`` and would otherwise fire network health checks
during seeding (the review's M5 fix).

Each seed row: a template ``ExternalLink`` (URL with ``{lat}``/``{lon}``/
``{name}`` placeholders + example vars) + one PUBLIC ``ExternalAction``
scoping it. Re-running reports what was created vs already present.
"""

from __future__ import annotations

from typing import Any, override

from django.core.management.base import BaseCommand, CommandParser
from django.db import transaction

from server.apps.categories.models import Category
from server.apps.external_links.models import ExternalAction, ExternalLink

#: The kind categories (identifier -> scope). ``map.transport`` is
#: ensured by the seed itself (it is not part of the geoplace kinds
#: migration); amenity/natural exist via 0002_create_geoplace_categories.
KIND_TRANSPORT = "map.transport"
#: Map views apply to these geoplace kinds (empty kinds = any point).
KIND_POINT_MAPS = ["map.amenity", "map.natural"]

#: Coordinate examples per format family (Google wants lat,lon — Mapy
#: wants lon,lat; per-row examples keep each link self-documenting).
_EX_LATLON = {"lat": "46.9311", "lon": "7.4162", "name": "Bern"}
_EX_FROMTO_GOOGLE = {
    "from": "46.9480,7.4474",
    "lat": "46.4954",
    "lon": "7.6750",
}
_EX_FROMTO_MAPY = {
    "from": "7.4474,46.9480",
    "lat": "46.4954",
    "lon": "7.6750",
}
_EX_FROMTO_PLACE = {"from": "Interlaken Ost", "to": "Grindelwald"}

#: url template, label, countries ([] = global), kinds, order,
#: template_vars example. Map views are scoped to the point geoplace
#: kinds; planners are any-point (destination typed by the client).
SEED_ACTIONS: list[dict[str, Any]] = [
    # ── National journey planner (transport stops) ──────────────
    {
        # Owner-verified simplified form: stops=From~To (names; the SBB UI
        # appends _I<DiDok> disambiguation ids it resolves itself),
        # day={date} (selected date, defaults to tomorrow), {lang} for
        # the de/fr/it/en SPA path.
        "url": "https://www.sbb.ch/{lang}?stops={from}~{to}&day={date}&moment=dep",
        "label": "SBB Timetable",
        "countries": ["CH"],
        "kinds": [KIND_TRANSPORT],
        "order": 10,
        "template_vars": {
            **_EX_FROMTO_PLACE,
            "date": "2026-10-30",
            "lang": "de",
        },
    },
    # ── Map views (geoplace kinds: amenity + natural) ────────────
    {
        "url": "https://www.google.com/maps/search/?api=1&query={lat},{lon}",
        "label": "Google Maps",
        "countries": [],
        "kinds": KIND_POINT_MAPS,
        "order": 100,
    },
    {
        # Site-native form (owner-verified): id and x/y carry the same
        # coordinates; source=coor+id puts the dot marker on the map.
        "url": "https://mapy.com/en/turisticka?source=coor&id={lon},{lat}&x={lon}&y={lat}&z=16",
        "label": "Mapy",
        "countries": [],
        "kinds": KIND_POINT_MAPS,
        "order": 120,
    },
    {
        # Komoot planner with the destination pre-set (owner-verified):
        # p[0] empty = unset start, p[1][loc] = destination point.
        "url": "https://www.komoot.com/plan/@{lat},{lon},13z?p[0]&p[1][loc]={lat},{lon}",
        "label": "Komoot",
        "countries": [],
        "kinds": KIND_POINT_MAPS,
        "order": 130,
    },
    {
        # Strava map experience (owner-verified): #zoom/lat/lon — note
        # lat FIRST here (unlike the legacy heatmap URLs). Full detail
        # needs a (free) Strava login.
        "url": "https://www.strava.com/maps#16/{lat}/{lon}",
        "label": "Strava",
        "countries": [],
        "kinds": KIND_POINT_MAPS,
        "order": 140,
    },
    # ── Route planners (any point, from/to) ──────────────────────
    {
        "url": "https://www.google.com/maps/dir/?api=1&origin={from}&destination={lat},{lon}",
        "label": "Google Maps Route",
        "countries": [],
        "kinds": [],
        "order": 150,
        "template_vars": _EX_FROMTO_GOOGLE,
    },
    {
        "url": "https://mapy.com/fnc/v1/route?start={from}&end={lon},{lat}&routeType=foot_hiking",
        "label": "Mapy Route",
        "countries": [],
        "kinds": [],
        "order": 160,
        "template_vars": _EX_FROMTO_MAPY,
    },
    # ── Point weather (any point, global) ────────────────────────
    {
        "url": "https://www.meteoblue.com/en/weather/forecast/spot?lat={lat}&lon={lon}",
        "label": "meteoblue",
        "countries": [],
        "kinds": [],
        "order": 200,
    },
]

#: Fallback example template vars (docs + future health checks).
TEMPLATE_VARS_EXAMPLE = _EX_LATLON


def _ensure_kinds() -> None:
    """Create the map.transport kind under the map root if missing.

    The geoplace kinds (admin/amenity/natural) come from migration
    0002_create_geoplace_categories; transport stops are a separate
    feature family, so the seed provisions their kind itself.
    """
    root, _root_created = Category.objects.get_or_create(
        slug="map", parent=None, defaults={"name": "Map"}
    )
    Category.objects.get_or_create(
        slug="transport",
        parent=root,
        defaults={"name": "Transport"},
    )


class Command(BaseCommand):
    help = "Seed the open-in action registry (additive-only)."

    @override
    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be created without writing.",
        )

    @override
    def handle(self, *args: str, **options: Any) -> None:
        dry_run = options["dry_run"]
        created = skipped = 0
        kind_cache: dict[str, Category | None] = {}
        _ensure_kinds()

        for row in SEED_ACTIONS:
            link, link_created = ExternalLink.objects.get_or_create(
                url=row["url"],
                defaults={
                    "label": row["label"],
                    "template_vars": dict(
                        row.get("template_vars", TEMPLATE_VARS_EXAMPLE)
                    ),
                    "run_health_check": False,  # seeds never health-check
                },
            )
            if link_created:
                link.save(skip_health_check=True)
                created += 1
                self.stdout.write(f"  + link: {row['label']}")
            else:
                skipped += 1

            if ExternalAction.objects.filter(link=link, user=None).exists():
                continue  # additive-only: never touch existing actions

            action = ExternalAction(link=link, user=None, order=row["order"])
            if row["countries"]:
                action.countries = row["countries"]
            if not dry_run:
                with transaction.atomic():
                    action.save()
                    for kind_id in row["kinds"]:
                        if kind_id not in kind_cache:
                            kind_cache[kind_id] = Category.objects.filter(
                                identifier=kind_id, is_active=True
                            ).first()  # type: ignore[assignment]  # optional category
                        resolved = kind_cache[kind_id]
                        if resolved is not None:
                            action.kinds.add(resolved)
                self.stdout.write(f"  + action: {row['label']}")

        verb = "Would create" if dry_run else "Seeded"
        self.stdout.write(
            self.style.SUCCESS(
                f"{verb}: {created} new links, {len(SEED_ACTIONS) - created} "
                f"existing links reused."
            )
        )

"""Background history move for the geoplace-availability change (design D6).

Idempotent by natural key ``(geo_place, availability_date, first_checked)``;
resumable by source-id ranges — the cursor is over *source*
``HutAvailabilityHistory`` ids (target rows get fresh auto-increment ids;
hut PKs are never copied). The move snapshots the max source id and the
start time up front and skips rows with ``first_checked >= start``, so it
never touches events from its own runtime or later — the dual-write path
(Phase C) stamps rows in a strictly later epoch, making path overlap
impossible by construction. History ordering is exclusively
``(availability_date, first_checked)``; nothing here orders semantically by
id (the id range is only a scan cursor).
"""

from __future__ import annotations

import datetime

from django.db import models
from django.utils import timezone

from .models import (
    GeoPlaceAvailability,
    GeoPlaceAvailabilityHistory,
    HutAvailabilityHistory,
)
from .place_link import hut_slug_to_place_ids

DEFAULT_BATCH_SIZE = 5000


def snapshot() -> tuple[int, datetime.datetime]:
    """Max source id + the move's epoch start (rows at/after it are skipped)."""
    agg = HutAvailabilityHistory.objects.aggregate(max_id=models.Max("id"))
    return agg["max_id"] or 0, timezone.now()


def chunk_ranges(
    max_id: int, batch_size: int, id_from: int = 0
) -> list[tuple[int, int]]:
    """Half-open ``(lo, hi]`` source-id ranges covering ``id_from..max_id``."""
    ranges = []
    lo = id_from
    while lo < max_id:
        hi = min(lo + batch_size, max_id)
        ranges.append((lo, hi))
        lo = hi
    return ranges


def move_chunk(
    id_from: int,
    id_to: int,
    started_at: datetime.datetime,
    *,
    dry_run: bool = False,
) -> dict:
    """Move one ``(lo, hi]`` source-id range into the place history table.

    Returns counters: ``moved``, ``skipped_existing``, ``unmatched`` (slugs),
    ``availability_missing``. Safe to re-run (natural-key dedupe) and safe to
    run in parallel with other disjoint chunks.
    """
    rows = list(
        HutAvailabilityHistory.objects.select_related("hut").filter(
            id__gt=id_from, id__lte=id_to, first_checked__lt=started_at
        )
    )
    stats = {
        "moved": 0,
        "skipped_existing": 0,
        "unmatched": [],
        "availability_missing": 0,
    }
    if not rows:
        return stats

    mapping = hut_slug_to_place_ids()

    # Natural-key dedupe + (place, date) → place-availability-row lookup,
    # scoped to the places this chunk touches.
    place_ids = {mapping[r.hut.slug] for r in rows if r.hut.slug in mapping}
    dates = {r.availability_date for r in rows}
    existing_keys = set(
        GeoPlaceAvailabilityHistory.objects.filter(
            geo_place_id__in=place_ids
        ).values_list("geo_place_id", "availability_date", "first_checked")
    )
    avail_map = {
        (a.geo_place_id, a.availability_date): a.pk
        for a in GeoPlaceAvailability.objects.filter(
            geo_place_id__in=place_ids, availability_date__in=dates
        )
    }

    to_create: list[GeoPlaceAvailabilityHistory] = []
    for row in rows:
        place_id = mapping.get(row.hut.slug)
        if place_id is None:
            if row.hut.slug not in stats["unmatched"]:
                stats["unmatched"].append(row.hut.slug)
            continue
        key = (place_id, row.availability_date, row.first_checked)
        if key in existing_keys:
            stats["skipped_existing"] += 1
            continue
        avail_id = avail_map.get((place_id, row.availability_date))
        if avail_id is None:
            stats["availability_missing"] += 1
        to_create.append(
            GeoPlaceAvailabilityHistory(
                availability_id=avail_id,
                geo_place_id=place_id,
                availability_date=row.availability_date,
                free=row.free,
                total=row.total,
                free_tolerance=row.free_tolerance,
                occupancy_percent=row.occupancy_percent,
                occupancy_status=row.occupancy_status,
                reservation_status=row.reservation_status,
                hut_type_id=row.hut_type_id,
                first_checked=row.first_checked,
                last_checked=row.last_checked,
            )
        )
        existing_keys.add(key)

    if not dry_run and to_create:
        GeoPlaceAvailabilityHistory.objects.bulk_create(to_create)
    stats["moved"] = len(to_create)
    return stats


def run_chunk(
    id_from: int, id_to: int, started_at_iso: str, dry_run: bool = False
) -> dict:
    """django-q entry point — plain serializable args, delegates to
    :func:`move_chunk`."""
    return move_chunk(
        id_from,
        id_to,
        datetime.datetime.fromisoformat(started_at_iso),
        dry_run=dry_run,
    )

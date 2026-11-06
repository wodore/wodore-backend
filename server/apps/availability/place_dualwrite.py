"""Place-side mirror of the hut availability writes (Phase C dual-write).

Geoplace-availability design D7: while hut readers still exist, the update
pipeline writes BOTH the hut tables (authoritative until Phase E) and the
GeoPlace tables — computing each event once (same ``now``, same values) and
persisting it twice, inside the same transaction, so content equality holds
by construction.

Huts without a place association are skipped on the place side and logged
(design D5); their hut-side rows stay authoritative until Phase E. Two
transitional artifacts are accepted and documented:

- Rows created between the Phase B backfill and the Phase C deploy appear on
  the place side with the hut row's ``first_checked`` (inherited on create).
- Place rows that drifted during the same window (a change landed hut-side
  only) converge on the first dual-write run; the place side records one
  extra change event for that convergence — content equality is restored,
  history keeps one additional correction entry.

Write discipline carried over verbatim from ``services.py`` (design D6):
same batch size, same statement timeout, same chunked bulk writes. This
module dies with the hut write path in Phase E.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any, TypedDict

from django.db import connection, transaction
from django.utils import timezone

from server.apps.organizations.models import Organization

from .models import (
    GeoPlaceAvailability,
    GeoPlaceAvailabilityHistory,
    GeoPlaceAvailabilityStatus,
)
from .place_link import hut_slug_to_place_ids

logger = logging.getLogger(__name__)

# Carried over verbatim from services.py — the mirror must not write with a
# looser discipline than the hut side.
BULK_WRITE_BATCH_SIZE = 500
BATCH_STATEMENT_TIMEOUT_MS = 120_000


class MirrorBatchStats(TypedDict):
    """Counters for one mirrored batch (see :func:`mirror_batch`)."""

    created: int
    updated: int
    unchanged: int
    history: int
    unmatched: list[str]


def mirror_batch(
    batch: list[tuple[Any, Any]],
    now: datetime.datetime | None = None,
    update_history_last_checked: bool = False,
    mapping: dict[str, int] | None = None,
) -> MirrorBatchStats:
    """Mirror one ``(hut, hut_booking)`` batch onto the place tables.

    Must run inside the caller's transaction (atomic with the hut-side
    writes — a failure rolls back both sides). ``mapping`` may be passed
    in when a caller processes several batches (review N1: one
    association read per run instead of per batch). Returns counters:
    ``created``/``updated``/``unchanged`` place rows, ``history`` entries,
    and ``unmatched`` hut slugs that were skipped.
    """
    if now is None:
        now = timezone.now()

    if mapping is None:
        mapping = hut_slug_to_place_ids()
    linked = [
        (hut, hut_booking, mapping[hut.slug])
        for hut, hut_booking in batch
        if hut.slug in mapping
    ]
    unmatched = sorted({hut.slug for hut, _ in batch if hut.slug not in mapping})
    if unmatched:
        logger.info(
            "geoplace dual-write: %d unmatched hut(s) skipped: %s",
            len(unmatched),
            ", ".join(unmatched),
        )
    stats = {
        "created": 0,
        "updated": 0,
        "unchanged": 0,
        "history": 0,
        "unmatched": unmatched,
    }
    if not linked:
        return stats

    # Defensive savepoint (review N2): callers wrap us in their own
    # transaction (the batch atomic block); the nested atomic keeps a bare
    # future caller from writing place rows outside a transaction.
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                f"SET LOCAL statement_timeout = {int(BATCH_STATEMENT_TIMEOUT_MS)}"
            )

        org_slugs = {hut_booking.source for _, hut_booking, _ in linked}
        orgs_by_slug = {
            org.slug: org for org in Organization.objects.filter(slug__in=org_slugs)
        }

        all_place_ids = [place_id for _, _, place_id in linked]
        all_dates = []
        for _, hut_booking, _ in linked:
            all_dates.extend([booking.date for booking in hut_booking.bookings])

        unique_hut_types = set()
        for _, hut_booking, _ in linked:
            for booking in hut_booking.bookings:
                if booking.hut_type:
                    unique_hut_types.add(booking.hut_type)
        hut_type_cache = {}
        if unique_hut_types:
            from server.apps.huts.models import HutTypeHelper

            for hut_type_slug in unique_hut_types:
                hut_type_cache[hut_type_slug] = HutTypeHelper.values.get(hut_type_slug)

        # Existing place rows for the batch window
        existing = {
            (avail.geo_place_id, avail.availability_date): avail
            for avail in GeoPlaceAvailability.objects.filter(
                geo_place_id__in=all_place_ids, availability_date__in=all_dates
            )
        }
        # Hut rows for the same window — only used to inherit ``first_checked``
        # on the create branch (B→C gap rows keep their original timestamp).
        from .models import HutAvailability

        hut_rows = {
            (avail.hut_id, avail.availability_date): avail
            for avail in HutAvailability.objects.filter(
                hut_id__in=[hut.id for hut, _, _ in linked],
                availability_date__in=all_dates,
            )
        }

        to_create: list[GeoPlaceAvailability] = []
        to_update: list[GeoPlaceAvailability] = []
        unchanged: list[GeoPlaceAvailability] = []
        unchanged_ids: list[int] = []
        new_history: list[GeoPlaceAvailabilityHistory] = []
        queued_new: dict[tuple[int, Any], GeoPlaceAvailability] = {}

        for hut, hut_booking, place_id in linked:
            source_org = orgs_by_slug.get(hut_booking.source)
            if not source_org:
                continue  # the hut side already recorded the failure
            source_hut_id = str(hut_booking.source_id)

            for booking in hut_booking.bookings:
                reservation_status = (
                    booking.reservation_status.value
                    if hasattr(booking.reservation_status, "value")
                    else str(booking.reservation_status)
                )
                occupancy_status = (
                    booking.occupancy_status.value
                    if hasattr(booking.occupancy_status, "value")
                    else str(booking.occupancy_status)
                )
                hut_type_obj = (
                    hut_type_cache.get(booking.hut_type) if booking.hut_type else None
                )

                availability = existing.get((place_id, booking.date))
                if availability is None:
                    new_avail = queued_new.get((place_id, booking.date))
                    if new_avail is None:
                        # Inherit first_checked from the hut row when one
                        # exists (B→C window); else this batch's ``now``.
                        hut_row = hut_rows.get((hut.id, booking.date))
                        new_avail = GeoPlaceAvailability(
                            geo_place_id=place_id,
                            availability_date=booking.date,
                            source_organization=source_org,
                            source_id=source_hut_id,
                            free=booking.free,
                            total=booking.total,
                            free_tolerance=booking.free_tolerance,
                            occupancy_percent=booking.occupancy_percent,
                            occupancy_steps=booking.occupancy_steps,
                            occupancy_status=occupancy_status,
                            reservation_status=reservation_status,
                            link=booking.link or "",
                            hut_type=hut_type_obj,
                            first_checked=(hut_row.first_checked if hut_row else now),
                            last_checked=now,
                        )
                        queued_new[(place_id, booking.date)] = new_avail
                        to_create.append(new_avail)
                        stats["created"] += 1
                    else:
                        new_avail.free = booking.free
                        new_avail.total = booking.total
                        new_avail.free_tolerance = booking.free_tolerance
                        new_avail.occupancy_percent = booking.occupancy_percent
                        new_avail.occupancy_steps = booking.occupancy_steps
                        new_avail.occupancy_status = occupancy_status
                        new_avail.reservation_status = reservation_status
                        new_avail.link = booking.link or ""
                        new_avail.hut_type = hut_type_obj
                else:
                    changed = (
                        availability.free != booking.free
                        or availability.total != booking.total
                        or availability.free_tolerance != booking.free_tolerance
                        or availability.hut_type != hut_type_obj
                        or availability.reservation_status != reservation_status
                    )
                    if changed:
                        new_history.append(
                            GeoPlaceAvailabilityHistory(
                                availability=availability,
                                geo_place_id=place_id,
                                availability_date=availability.availability_date,
                                free=booking.free,
                                total=booking.total,
                                free_tolerance=booking.free_tolerance,
                                occupancy_percent=booking.occupancy_percent,
                                occupancy_status=occupancy_status,
                                reservation_status=reservation_status,
                                hut_type=hut_type_obj,
                                first_checked=now,
                                last_checked=now,
                            )
                        )
                        availability.free = booking.free
                        availability.total = booking.total
                        availability.free_tolerance = booking.free_tolerance
                        availability.occupancy_percent = booking.occupancy_percent
                        availability.occupancy_steps = booking.occupancy_steps
                        availability.occupancy_status = occupancy_status
                        availability.reservation_status = reservation_status
                        availability.link = booking.link or ""
                        availability.hut_type = hut_type_obj
                        availability.last_checked = now
                        to_update.append(availability)
                        stats["updated"] += 1
                    else:
                        availability.last_checked = now
                        unchanged.append(availability)
                        unchanged_ids.append(availability.id)
                        stats["unchanged"] += 1

        if to_create:
            created = GeoPlaceAvailability.objects.bulk_create(
                to_create, batch_size=BULK_WRITE_BATCH_SIZE
            )
            for avail in created:
                new_history.append(
                    GeoPlaceAvailabilityHistory(
                        availability=avail,
                        geo_place_id=avail.geo_place_id,
                        availability_date=avail.availability_date,
                        free=avail.free,
                        total=avail.total,
                        occupancy_percent=avail.occupancy_percent,
                        occupancy_status=avail.occupancy_status,
                        reservation_status=avail.reservation_status,
                        hut_type=avail.hut_type,
                        first_checked=avail.first_checked,
                        last_checked=avail.last_checked,
                    )
                )

        if to_update:
            GeoPlaceAvailability.objects.bulk_update(
                to_update,
                fields=[
                    "free",
                    "total",
                    "free_tolerance",
                    "occupancy_percent",
                    "occupancy_steps",
                    "occupancy_status",
                    "reservation_status",
                    "link",
                    "hut_type",
                    "last_checked",
                ],
                batch_size=BULK_WRITE_BATCH_SIZE,
            )

        if unchanged:
            GeoPlaceAvailability.objects.bulk_update(
                unchanged,
                fields=["last_checked"],
                batch_size=BULK_WRITE_BATCH_SIZE,
            )

        if new_history:
            GeoPlaceAvailabilityHistory.objects.bulk_create(
                new_history, batch_size=BULK_WRITE_BATCH_SIZE
            )
            stats["history"] = len(new_history)

        if update_history_last_checked and unchanged_ids:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE availability_geoplaceavailabilityhistory
                    SET last_checked = %s
                    WHERE id IN (
                        SELECT DISTINCT ON (availability_id, availability_date) id
                        FROM availability_geoplaceavailabilityhistory
                        WHERE availability_id = ANY(%s)
                          AND availability_date = ANY(%s)
                        ORDER BY availability_id, availability_date,
                                 first_checked DESC
                    )
                    """,
                    [now, unchanged_ids, list(set(all_dates))],
                )

    return stats


def mirror_status(
    successful_huts: list[Any],
    failed_huts: list[Any],
    now: datetime.datetime | None = None,
) -> None:
    """Mirror the end-of-run AvailabilityStatus block onto place status."""
    if not successful_huts and not failed_huts:
        return
    if now is None:
        now = timezone.now()

    mapping = hut_slug_to_place_ids()
    success_places = [
        mapping[hut.slug] for hut in successful_huts if hut.slug in mapping
    ]
    failed_places = [mapping[hut.slug] for hut in failed_huts if hut.slug in mapping]
    if not success_places and not failed_places:
        return

    existing = {
        status.geo_place_id: status
        for status in GeoPlaceAvailabilityStatus.objects.filter(
            geo_place_id__in=success_places + failed_places
        )
    }

    to_create: list[GeoPlaceAvailabilityStatus] = []
    to_update: list[GeoPlaceAvailabilityStatus] = []

    for place_id in success_places:
        status = existing.get(place_id)
        if status is not None:
            status.last_checked = now
            status.last_success = now
            status.has_data = True
            status.consecutive_failures = 0
            to_update.append(status)
        else:
            to_create.append(
                GeoPlaceAvailabilityStatus(
                    geo_place_id=place_id,
                    last_checked=now,
                    last_success=now,
                    has_data=True,
                    consecutive_failures=0,
                )
            )

    for place_id in failed_places:
        status = existing.get(place_id)
        if status is not None:
            status.last_checked = now
            status.consecutive_failures += 1
            to_update.append(status)
        else:
            to_create.append(
                GeoPlaceAvailabilityStatus(
                    geo_place_id=place_id,
                    last_checked=now,
                    consecutive_failures=1,
                )
            )

    if to_create:
        GeoPlaceAvailabilityStatus.objects.bulk_create(to_create)
    if to_update:
        GeoPlaceAvailabilityStatus.objects.bulk_update(
            to_update,
            fields=[
                "last_checked",
                "last_success",
                "has_data",
                "consecutive_failures",
            ],
        )


def mirror_mark_failure(huts: list[Any], now: datetime.datetime) -> None:
    """Mirror the per-hut fetch-failure ``mark_failure`` onto place status.

    ``now`` must be the same timestamp the hut side used (Phase C review
    F1) — the shared invariant keeps the place-driven cadence in step
    with the hut side's expectations.
    """
    mapping = hut_slug_to_place_ids()
    place_ids = [mapping[hut.slug] for hut in huts if hut.slug in mapping]
    for place_id in place_ids:
        status, _ = GeoPlaceAvailabilityStatus.objects.get_or_create(
            geo_place_id=place_id, defaults={"last_checked": now}
        )
        status.mark_failure(now=now)

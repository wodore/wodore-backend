"""Hut→place resolution for the geoplace-availability change (design D5).

A hut resolves to its place through the source association recorded by
``import_geoplaces`` — organization ``wodore``, ``source_id = hut.slug`` —
never via geoplace-slug equality. Huts without a matching place are exposed
by :func:`unmatched_huts` (the Phase E gate artifact) — reported, never
skipped silently.
"""

from __future__ import annotations

from django.db.models import QuerySet

from server.apps.geometries.models import GeoPlace, GeoPlaceSourceAssociation
from server.apps.huts.models import Hut

WODORE_ORG_SLUG = "wodore"


def hut_slug_to_place_ids() -> dict[str, int]:
    """Map ``hut.slug`` → ``GeoPlace`` pk via the wodore source association.

    Single indexed query over ``(organization.slug, source_id)``; the
    association's partial unique constraint guarantees at most one place per
    hut slug.
    """
    rows = (
        GeoPlaceSourceAssociation.objects.filter(
            organization__slug=WODORE_ORG_SLUG,
            source_id__isnull=False,
        )
        .exclude(source_id="")
        .values_list("source_id", "geo_place_id")
    )
    return dict(rows)


def resolve_place(hut: Hut, mapping: dict[str, int] | None = None) -> GeoPlace | None:
    """Resolve a hut to its place, or ``None`` when no association exists.

    Without ``mapping`` this issues ONE targeted query (the per-request
    path used by the Phase D controllers) instead of loading the full
    association map; batch callers pass a prebuilt ``mapping``.
    """
    if mapping is not None:
        place_id = mapping.get(hut.slug)
        if place_id is None:
            return None
        return GeoPlace.objects.filter(pk=place_id).first()
    return GeoPlace.objects.filter(
        source_associations__organization__slug=WODORE_ORG_SLUG,
        source_associations__source_id=hut.slug,
    ).first()


def unmatched_huts() -> QuerySet[Hut]:
    """Huts with availability data but no place association.

    The Phase E removal gate requires this set to be empty; the
    ``report_unmatched_huts`` command prints it.
    """
    mapping = hut_slug_to_place_ids()
    return (
        Hut.objects.filter(availabilities__isnull=False)
        .distinct()
        .exclude(slug__in=mapping.keys())
        .order_by("slug")
    )

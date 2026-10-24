from django.db import migrations

BATCH_SIZE = 2000

# Fields copied 1:1 from HutAvailability → GeoPlaceAvailability (straight
# column copy, no recompute — geoplace-availability design D6).
_AVAILABILITY_FIELDS = (
    "source_organization_id",
    "source_id",
    "availability_date",
    "free",
    "total",
    "free_tolerance",
    "occupancy_percent",
    "occupancy_steps",
    "occupancy_status",
    "reservation_status",
    "link",
    "hut_type_id",
    "first_checked",
    "last_checked",
)


def backfill(apps, schema_editor):
    """Copy current availability state + fetch status to the place tables.

    Joins each hut to its place through the wodore source association
    (design D5: organization "wodore", source_id = hut.slug). Unmatched
    huts are counted and printed, never skipped silently. Existing target
    rows are skipped, so a partially applied rerun is safe.
    """
    GeoPlaceSourceAssociation = apps.get_model("geometries", "GeoPlaceSourceAssociation")
    HutAvailability = apps.get_model("availability", "HutAvailability")
    AvailabilityStatus = apps.get_model("availability", "AvailabilityStatus")
    GeoPlaceAvailability = apps.get_model("availability", "GeoPlaceAvailability")
    GeoPlaceAvailabilityStatus = apps.get_model(
        "availability", "GeoPlaceAvailabilityStatus"
    )

    mapping = dict(
        GeoPlaceSourceAssociation.objects.filter(
            organization__slug="wodore", source_id__isnull=False
        )
        .exclude(source_id="")
        .values_list("source_id", "geo_place_id")
    )

    existing = set(
        GeoPlaceAvailability.objects.values_list("geo_place_id", "availability_date")
    )
    unmatched: set[str] = set()
    to_create = []
    copied = 0
    for row in HutAvailability.objects.select_related("hut").iterator(
        chunk_size=BATCH_SIZE
    ):
        place_id = mapping.get(row.hut.slug)
        if place_id is None:
            unmatched.add(row.hut.slug)
            continue
        key = (place_id, row.availability_date)
        if key in existing:
            continue
        existing.add(key)
        kwargs = {field: getattr(row, field) for field in _AVAILABILITY_FIELDS}
        to_create.append(
            GeoPlaceAvailability(geo_place_id=place_id, **kwargs)
        )
        copied += 1
        if len(to_create) >= BATCH_SIZE:
            GeoPlaceAvailability.objects.bulk_create(to_create)
            to_create = []
    if to_create:
        GeoPlaceAvailability.objects.bulk_create(to_create)

    status_copied = 0
    status_to_create = []
    for row in AvailabilityStatus.objects.select_related("hut").iterator(
        chunk_size=BATCH_SIZE
    ):
        place_id = mapping.get(row.hut.slug)
        if place_id is None:
            continue
        if GeoPlaceAvailabilityStatus.objects.filter(geo_place_id=place_id).exists():
            continue
        status_to_create.append(
            GeoPlaceAvailabilityStatus(
                geo_place_id=place_id,
                last_checked=row.last_checked,
                last_success=row.last_success,
                has_data=row.has_data,
                consecutive_failures=row.consecutive_failures,
            )
        )
        status_copied += 1
        if len(status_to_create) >= BATCH_SIZE:
            GeoPlaceAvailabilityStatus.objects.bulk_create(status_to_create)
            status_to_create = []
    if status_to_create:
        GeoPlaceAvailabilityStatus.objects.bulk_create(status_to_create)

    print(
        f"backfill_geoplace_availability: copied {copied} availability row(s), "
        f"{status_copied} status row(s); "
        f"{len(unmatched)} unmatched hut(s): {', '.join(sorted(unmatched)) or '-'}"
    )


def remove_backfill(apps, schema_editor):
    """Reverse: drop everything the forward pass created.

    Safe pre-Phase C: nothing but this migration writes the place tables,
    so deleting all their rows restores the pre-migration state exactly.
    """
    GeoPlaceAvailability = apps.get_model("availability", "GeoPlaceAvailability")
    GeoPlaceAvailabilityStatus = apps.get_model(
        "availability", "GeoPlaceAvailabilityStatus"
    )
    GeoPlaceAvailability.objects.all().delete()
    GeoPlaceAvailabilityStatus.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("availability", "0018_geoplaceavailabilitystatus_geoplaceavailability_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill, remove_backfill),
    ]

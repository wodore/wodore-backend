"""Unmanaged model over the ``availability_hut_features`` SQL view.

Phase D of the geoplace-availability change: readers serve from the place
tables while hut-keyed response fields (feature id/slug, geometry, type
classification) stay hut-side until Phase E (design D7). The view joins
``GeoPlaceAvailability`` through the wodore source association onto
``huts_hut`` so the ORM reaches every hut field via the normal FK path —
the GeoJSON controller keeps its field references unchanged and its output
byte-identical.

Read-only by construction: never write through this model. The view and the
tile-function replacement live in migration
``0020_reader_cutover_place_tables``.
"""

from django.db import models

from server.apps.categories.models import Category
from server.apps.geometries.models import GeoPlace
from server.apps.huts.models import Hut
from server.apps.organizations.models import Organization


class AvailabilityHutFeature(models.Model):
    """One place availability row joined to its hut (read-only view)."""

    # The place-row id: unique because the wodore association is unique on
    # both (organization, source_id) and (organization, geo_place).
    id = models.BigIntegerField(primary_key=True)
    geo_place = models.ForeignKey(
        GeoPlace,
        on_delete=models.DO_NOTHING,
        db_constraint=False,
        related_name="+",
    )
    hut = models.ForeignKey(
        Hut,
        on_delete=models.DO_NOTHING,
        db_constraint=False,
        related_name="+",
    )
    source_organization = models.ForeignKey(
        Organization,
        on_delete=models.DO_NOTHING,
        db_constraint=False,
        related_name="+",
    )
    hut_type = models.ForeignKey(
        Category,
        null=True,
        on_delete=models.DO_NOTHING,
        db_constraint=False,
        related_name="+",
    )
    source_id = models.CharField(max_length=50)
    availability_date = models.DateField()
    free = models.PositiveSmallIntegerField(null=True)
    total = models.PositiveSmallIntegerField(null=True)
    free_tolerance = models.PositiveSmallIntegerField(null=True)
    occupancy_percent = models.FloatField(null=True)
    occupancy_steps = models.PositiveSmallIntegerField(null=True)
    occupancy_status = models.CharField(max_length=20)
    reservation_status = models.CharField(max_length=20)
    link = models.URLField(max_length=500, blank=True, default="")
    first_checked = models.DateTimeField()
    last_checked = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "availability_hut_features"

    def __str__(self) -> str:
        return f"{self.hut} - {self.availability_date} ({self.free}/{self.total})"

"""Martin function source: hut availability as vector tiles.

``get_availability_for_tiles(z, x, y, query_params jsonb)`` (migration
``0016_add_availability_tile_function``) is registered in
``tile_server/config/martin.yaml`` as the ``availability`` function source
and serves one feature per hut with the per-day availability series
flattened into scalar MVT properties (MVT attributes cannot carry nested
arrays/objects).

URL → function mapping (Martin passes every URL query param as a string in
``query_params``):

``/availability/{z}/{x}/{y}?date=2026-02-14&days=4``

==================  =========================================================
Parameter           Meaning
==================  =========================================================
``date``            REQUIRED start date ``YYYY-MM-DD`` — always sent
                    explicitly by the frontend ("now" logic stays
                    client-side so every URL is edge-cacheable).
                    Missing/invalid input yields an **empty tile**, not a
                    default.
``days``            Flattened series length, 1..8. Default 4 (matches the
                    four day-columns the hut overlay renders).
``days_max_zoom``   Below this zoom only day 0 is served. Default 7;
                    ``0`` disables the clamp. Keeps low-zoom tiles small
                    without client-side zoom bookkeeping.
``cache_ttl``       DB tile-cache TTL in seconds. Default 900 (15 min);
                    ``0`` disables caching.
==================  =========================================================

Feature properties (per day ``N`` in ``0..days-1``):

``dN_status``        occupancy bucket (empty/low/medium/high/full/
                     free_unknown/unknown)
``dN_free``,         counts — absent when the source does not publish
``dN_total``         them for that day
``dN_type``          ``standard`` | ``reduced`` (hut type on that date) —
                     absent when the availability row carries no hut_type
``dN_type_identifier``
                     sprite-capable category identifier, and
``dN_type_color``     category color (SDF tinting)

plus feature-level ``slug``, ``capacity`` and ``days`` (how many day
columns this tile carries — style guard: ``["<", day, ["get", "days"]]``).

Properties outside the requested window are absent (NULLs are dropped by
``ST_AsMVT``), which distinguishes a server-side clamp (all features
report ``days: 1``) from a per-hut data gap (single day prop missing).

Tiles are cached in ``availability_tile_cache`` keyed
``(z, x, y, md5(params sans cache_ttl))`` with ``expires_at`` TTL; use
``cleanup_availability_tile_cache(hours)`` for housekeeping. The Martin
source advertises ``minzoom 5`` / ``maxzoom 9`` (deeper zooms overzoom the
z9 tiles client-side — no further requests) and
``Cache-Control: public, max-age=900``.
"""

from django.db import models


class AvailabilityTileCache(models.Model):
    """DB cache for ``get_availability_for_tiles`` (unmanaged).

    Created and owned by migration ``0016_add_availability_tile_function``;
    this model exists for introspection, tests and admin-style inspection.
    """

    z = models.IntegerField()
    x = models.IntegerField()
    y = models.IntegerField()
    params_hash = models.TextField()
    tile_data = models.BinaryField()
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    hits = models.IntegerField(default=0)

    class Meta:  # pyright: ignore[reportIncompatibleVariableOverride]
        managed = False
        db_table = "availability_tile_cache"
        verbose_name = "Availability Tile Cache"
        verbose_name_plural = "Availability Tile Cache"

    def __str__(self) -> str:
        return f"availability tile {self.z}/{self.x}/{self.y} ({self.params_hash[:8]})"

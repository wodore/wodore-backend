"""Bounding-box parsing for sweep commands.

Value format everywhere: ``lon_min,lat_min,lon_max,lat_max`` (WGS84
degrees, min < max). The admin form's bbox widget produces exactly this
string.

Boxes crossing the antimeridian are supported in either spelling:
longitudes outside ±180 (what map tools emit for regions spanning the
dateline, e.g. New Zealand as ``-202.88,-51.74,-160.53,-30.64``) or
in-range longitudes with ``lon_min > lon_max`` (``175,-50,-175,-40``).
Both parse into a two-envelope multipolygon meeting at ±180.
"""

import math

from django.contrib.gis.geos import GEOSGeometry, MultiPolygon, Polygon


def parse_bbox(value: str) -> GEOSGeometry:
    """Parse a bbox string into a WGS84 envelope.

    An antimeridian-crossing box (see the module docstring) returns a
    :class:`~django.contrib.gis.geos.MultiPolygon` of its two dateline
    halves; anything else a single
    :class:`~django.contrib.gis.geos.Polygon`.

    Raises ``ValueError`` with a user-presentable message on bad input.
    """
    parts = [part.strip() for part in value.split(",") if part.strip()]
    if len(parts) != 4:
        raise ValueError("bbox must be lon_min,lat_min,lon_max,lat_max")
    try:
        lon_min, lat_min, lon_max, lat_max = (float(part) for part in parts)
    except ValueError as exc:
        raise ValueError("bbox coordinates must be numbers") from exc
    if not all(math.isfinite(v) for v in (lon_min, lat_min, lon_max, lat_max)):
        raise ValueError("bbox coordinates must be numbers")
    if not (-90 <= lat_min < lat_max <= 90):
        raise ValueError(
            "bbox latitude out of range or min >= max (lon_min,lat_min,lon_max,lat_max)"
        )
    if lon_min == lon_max:
        raise ValueError(
            "bbox out of range or min >= max (lon_min,lat_min,lon_max,lat_max)"
        )
    if lon_max - lon_min >= 360:
        return Polygon.from_bbox((-180.0, lat_min, 180.0, lat_max))

    # Normalize the longitudes into [-180, 180) so dateline-crossing
    # boxes collapse onto the ±180 seam; +180 itself maps to the east
    # edge, so a box ending exactly at the dateline stays one envelope.
    start = ((lon_min + 180.0) % 360.0) - 180.0
    end = ((lon_max + 180.0) % 360.0) - 180.0
    if end == -180.0:
        end = 180.0
    if start < end:
        return Polygon.from_bbox((start, lat_min, end, lat_max))

    # Wrapped around the antimeridian: two envelopes meeting at ±180.
    return MultiPolygon(
        [
            Polygon.from_bbox((start, lat_min, 180.0, lat_max)),
            Polygon.from_bbox((-180.0, lat_min, end, lat_max)),
        ]
    )

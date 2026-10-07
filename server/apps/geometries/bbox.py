"""Bounding-box parsing for sweep commands.

Value format everywhere: ``lon_min,lat_min,lon_max,lat_max`` (WGS84
degrees, min < max). The admin form's bbox widget produces exactly this
string.
"""

from django.contrib.gis.geos import Polygon


def parse_bbox(value: str) -> Polygon:
    """Parse a bbox string into a WGS84 polygon envelope.

    Raises ``ValueError`` with a user-presentable message on bad input.
    """
    parts = [part.strip() for part in value.split(",") if part.strip()]
    if len(parts) != 4:
        raise ValueError("bbox must be lon_min,lat_min,lon_max,lat_max")
    try:
        lon_min, lat_min, lon_max, lat_max = (float(part) for part in parts)
    except ValueError as exc:
        raise ValueError("bbox coordinates must be numbers") from exc
    if not (-180 <= lon_min < lon_max <= 180 and -90 <= lat_min < lat_max <= 90):
        raise ValueError(
            "bbox out of range or min >= max (lon_min,lat_min,lon_max,lat_max)"
        )
    return Polygon.from_bbox((lon_min, lat_min, lon_max, lat_max))

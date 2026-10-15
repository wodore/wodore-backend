"""Tests for ``server.apps.geometries.bbox.parse_bbox``.

Plain envelopes, antimeridian-crossing boxes (both spellings: longitudes
outside ±180 as map tools emit them for dateline-spanning regions, and
in-range ``lon_min > lon_max``), and the error contract.
"""

import pytest

from django.contrib.gis.geos import MultiPolygon, Polygon

from server.apps.geometries.bbox import parse_bbox

# New Zealand incl. the Chathams, as drawing tools emit it: the box runs
# from 157.11317°E across the dateline to 199.46268°E (= -160.53732).
NZ_BBOX = "-202.88683,-51.74934,-160.53732,-30.64888"


def test_plain_envelope():
    poly = parse_bbox("7.5,46.0,8.5,46.8")
    assert isinstance(poly, Polygon)
    # No explicit SRID, matching from_bbox: GeoDjango lookups assume the
    # field's SRID (4326) — same convention as before antimeridian support.
    assert poly.srid is None
    assert poly.extent == (7.5, 46.0, 8.5, 46.8)


def test_negative_envelope():
    poly = parse_bbox("-179.0,-50.0,-178.0,-49.0")
    assert isinstance(poly, Polygon)
    assert poly.extent == (-179.0, -50.0, -178.0, -49.0)


def test_world_envelope_unchanged():
    poly = parse_bbox("-180.0,-90.0,180.0,90.0")
    assert isinstance(poly, Polygon)
    assert poly.extent == (-180.0, -90.0, 180.0, 90.0)


def test_east_edge_on_dateline_stays_single():
    """A box ending exactly at +180 needs no wrap."""
    poly = parse_bbox("165.0,0.0,180.0,10.0")
    assert isinstance(poly, Polygon)
    assert poly.extent == (165.0, 0.0, 180.0, 10.0)


def test_west_edge_on_dateline_stays_single():
    poly = parse_bbox("-180.0,0.0,-170.0,10.0")
    assert isinstance(poly, Polygon)
    assert poly.extent == (-180.0, 0.0, -170.0, 10.0)


def test_antimeridian_out_of_range_longitudes():
    """NZ-style lons below -180 wrap into a two-envelope multipolygon."""
    multi = parse_bbox(NZ_BBOX)
    assert isinstance(multi, MultiPolygon)
    assert len(multi) == 2
    west, east = sorted(multi, key=lambda g: g.extent[0])
    assert west.extent == pytest.approx((-180.0, -51.74934, -160.53732, -30.64888))
    assert east.extent == pytest.approx((157.11317, -51.74934, 180.0, -30.64888))


def test_antimeridian_past_positive_180():
    """The mirrored spelling (lons above +180) wraps the same way."""
    multi = parse_bbox("170.0,-50.0,190.0,-40.0")
    assert isinstance(multi, MultiPolygon)
    assert len(multi) == 2
    west, east = sorted(multi, key=lambda g: g.extent[0])
    assert west.extent == pytest.approx((-180.0, -50.0, -170.0, -40.0))
    assert east.extent == pytest.approx((170.0, -50.0, 180.0, -40.0))


def test_antimeridian_in_range_wrapped():
    """In-range longitudes with lon_min > lon_max wrap the dateline."""
    multi = parse_bbox("175.0,-50.0,-175.0,-40.0")
    assert isinstance(multi, MultiPolygon)
    assert len(multi) == 2
    assert sorted(g.extent for g in multi) == [
        (-180.0, -50.0, -175.0, -40.0),
        (175.0, -50.0, 180.0, -40.0),
    ]


def test_lon_span_over_360_collapses_to_world():
    poly = parse_bbox("-400.0,-10.0,50.0,10.0")
    assert isinstance(poly, Polygon)
    assert poly.extent == (-180.0, -10.0, 180.0, 10.0)


@pytest.mark.parametrize(
    "value",
    [
        "not,a,bbox",
        "1,2,3",
        "1,2,3,4,5",
        "100,0,100,10",  # zero-width longitude
        "0,-91,10,0",  # latitude out of range
        "0,0,10,91",
        "0,5,10,5",  # lat min >= max
        "nan,0,10,10",
        "0,0,inf,10",
    ],
)
def test_invalid_raises(value):
    with pytest.raises(ValueError, match="bbox"):
        parse_bbox(value)

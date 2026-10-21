"""Tests for the ``availability`` Martin function source.

``get_availability_for_tiles(z, x, y, query_params jsonb)`` (migration
``0016_add_availability_tile_function``) serves one MVT feature per hut
with the per-day availability series flattened into scalar properties.

These tests decode the generated protobuf (small hand-rolled MVT reader —
the lane venv has no mapbox-vector-tile) and assert on the decoded feature
properties: param handling (date/days/days_max_zoom), the flattened
per-day shape, hut_type enrichment and the DB tile cache.
"""

from __future__ import annotations

import datetime
import json
import math
import struct
from collections.abc import Iterator
from typing import Any

import pytest

from django.contrib.gis.geos import Point
from django.db import connection
from django.utils import timezone

from server.apps.availability.tiles import AvailabilityTileCache
from server.apps.categories.models import Category
from server.apps.huts.models import Hut
from server.apps.organizations.models import Organization

from .models import HutAvailability

# Test hut sits on the Rätikon (lon 8.5 / lat 46.5); the helper computes
# the covering tile per zoom so the tests never hardcode tile coords.
HUT_LON, HUT_LAT = 8.5, 46.5


# ── helpers ──────────────────────────────────────────────────────────────


def _tile_for(lon: float, lat: float, zoom: int) -> tuple[int, int]:
    """Web-mercator tile covering a coordinate (slippy-map tilenames)."""
    n = 2.0**zoom
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n)
    return x, y


def _read_varint(buf: bytes, i: int) -> tuple[int, int]:
    shift = result = 0
    while True:
        b = buf[i]
        i += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, i
        shift += 7


def _parse_fields(buf: bytes) -> Iterator[tuple[int, int, int | bytes]]:
    """Yield (field_number, wire_type, payload) for a protobuf message.

    Wire type 0 (varint) yields an ``int`` payload; wire types 1/2/5
    (fixed64/length-delimited/fixed32) yield raw ``bytes``.
    """
    i = 0
    while i < len(buf):
        key, i = _read_varint(buf, i)
        fno, wt = key >> 3, key & 7
        if wt == 0:
            v, i = _read_varint(buf, i)
            yield fno, wt, v
        elif wt == 2:
            ln, i = _read_varint(buf, i)
            yield fno, wt, buf[i : i + ln]
            i += ln
        elif wt == 5:
            yield fno, wt, buf[i : i + 4]
            i += 4
        elif wt == 1:
            yield fno, wt, buf[i : i + 8]
            i += 8
        else:
            msg = f"unexpected wire type {wt}"
            raise ValueError(msg)


def _decode_value(raw: bytes) -> Any:
    """Decode a vector-tile ``Value`` message."""
    for fno, _wt, payload in _parse_fields(raw):
        if fno == 1 and isinstance(payload, bytes):
            return payload.decode()
        if fno == 2 and isinstance(payload, bytes):
            return struct.unpack("<f", payload)[0]
        if fno == 3 and isinstance(payload, bytes):
            return struct.unpack("<d", payload)[0]
        if fno in (4, 5, 6, 7) and isinstance(payload, int):
            return bool(payload) if fno == 7 else payload
    return None


def decode_mvt(tile: bytes) -> list[dict[str, Any]]:
    """Decode MVT bytes into ``[{name, features: [{props}]}]``."""
    layers: list[dict[str, Any]] = []
    if not tile:
        return layers
    for fno, wt, payload in _parse_fields(tile):
        # Tile.layers = field 3, length-delimited
        if fno != 3 or wt != 2 or not isinstance(payload, bytes):
            continue
        layer: dict[str, Any] = {"features": [], "keys": [], "values": []}
        for lf, lwt, lp in _parse_fields(payload):
            if lwt != 2 or not isinstance(lp, bytes):
                continue  # version/extent are varints — irrelevant here
            if lf == 1:
                layer["name"] = lp.decode()
            elif lf == 2:
                feature: dict[str, Any] = {"tags": []}
                for ff, fw, fp in _parse_fields(lp):
                    if ff == 2 and fw == 2 and isinstance(fp, bytes):
                        tags: list[int] = []
                        j = 0
                        while j < len(fp):
                            v, j = _read_varint(fp, j)
                            tags.append(v)
                        feature["tags"] = tags
                    elif ff == 3 and isinstance(fp, int):
                        feature["type"] = fp
                layer["features"].append(feature)
            elif lf == 3:
                layer["keys"].append(lp.decode())
            elif lf == 4:
                layer["values"].append(_decode_value(lp))
        for feature in layer["features"]:
            tags = feature.pop("tags")
            feature["props"] = {
                layer["keys"][tags[i]]: layer["values"][tags[i + 1]]
                for i in range(0, len(tags), 2)
            }
        layers.append(layer)
    return layers


def fetch_tile(z: int, x: int, y: int, params: dict | None = None) -> bytes:
    with connection.cursor() as cur:
        cur.execute(
            "SELECT get_availability_for_tiles(%s, %s, %s, %s::jsonb)",
            [z, x, y, json.dumps(params or {})],
        )
        return cur.fetchone()[0]


def feature_by_slug(tile: bytes, slug: str) -> dict[str, Any] | None:
    for layer in decode_mvt(tile):
        for feature in layer["features"]:
            if feature["props"].get("slug") == slug:
                return feature["props"]
    return None


# ── fixtures / data ──────────────────────────────────────────────────────

TODAY = timezone.now().date()  # UTC date — matches the function default


@pytest.fixture
def hut_types():
    parent = Category.objects.create(slug="accommodation")
    open_type = Category.objects.create(
        slug="alpinehut-open", parent=parent, color="#25BF5E", order=1
    )
    closed_type = Category.objects.create(
        slug="alpinehut-closed", parent=parent, color="#961A17", order=2
    )
    return open_type, closed_type


@pytest.fixture
def hut(hut_types):
    open_type, closed_type = hut_types
    return Hut.objects.create(
        slug="test-hut",
        name="Test Hut",
        location=Point(HUT_LON, HUT_LAT, srid=4326),
        is_active=True,
        is_public=True,
        country_field="CH",
        hut_type_open=open_type,
        hut_type_closed=closed_type,
    )


def _reset_pk_sequence(model) -> None:
    """Sync a table's ``id`` sequence with ``MAX(id)``.

    Test databases cloned from the dev/template data contain rows
    inserted with explicit ids, leaving the sequence behind; creating
    new rows would collide with existing pks otherwise.
    (Same helper as meteo/tests.py.)
    """
    table = model._meta.db_table
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT setval(pg_get_serial_sequence(%s, 'id'), "
            f"COALESCE((SELECT MAX(id) FROM {table}), 1))",
            [table],
        )


def _add_availability(hut, day_offset, *, free, total, hut_type, status="medium"):
    now = timezone.now()
    _reset_pk_sequence(Organization)
    return HutAvailability.objects.create(
        hut=hut,
        source_organization=Organization.objects.create(
            slug=f"org-{hut.slug}-{day_offset}"
        ),
        source_id="src-1",
        availability_date=TODAY + datetime.timedelta(days=day_offset),
        free=free,
        total=total,
        occupancy_status=status,
        reservation_status="possible",
        hut_type=hut_type,
        first_checked=now,
        last_checked=now,
    )


# ── tile content ─────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestAvailabilityTiles:
    def test_flattened_day_properties(self, hut, hut_types):
        """A hut with two days of data yields d0/d1 props incl. hut type."""
        open_type, _ = hut_types
        _add_availability(hut, 0, free=5, total=20, hut_type=open_type)
        _add_availability(hut, 1, free=0, total=20, hut_type=open_type, status="full")

        x, y = _tile_for(HUT_LON, HUT_LAT, 9)
        tile = fetch_tile(9, x, y, {"date": TODAY.isoformat(), "cache_ttl": 0})

        props = feature_by_slug(tile, "test-hut")
        assert props is not None
        assert props["d0_status"] == "medium"
        assert props["d0_free"] == 5
        assert props["d0_total"] == 20
        assert props["d1_status"] == "full"
        assert props["d1_free"] == 0
        assert props["days"] == 4  # requested days, not the hut's data length
        assert props["capacity"] == 20
        # hut type enrichment (sprite-ready identifier + color)
        assert props["d0_type"] == "standard"
        assert props["d0_type_identifier"] == "accommodation.alpinehut-open"
        assert props["d0_type_color"] == "#25BF5E"
        # days beyond the hut's data carry no props at all
        assert "d2_status" not in props

    def test_reduced_type_discriminator(self, hut, hut_types):
        """hut_type == hut.hut_type_closed → 'reduced'."""
        _, closed_type = hut_types
        _add_availability(hut, 0, free=3, total=10, hut_type=closed_type)

        x, y = _tile_for(HUT_LON, HUT_LAT, 9)
        tile = fetch_tile(9, x, y, {"date": TODAY.isoformat(), "cache_ttl": 0})

        props = feature_by_slug(tile, "test-hut")
        assert props is not None
        assert props["d0_type"] == "reduced"
        assert props["d0_type_color"] == "#961A17"

    def test_null_hut_type_omits_type_props(self, hut):
        """Availability rows without hut_type still render the day."""
        _add_availability(hut, 0, free=1, total=2, hut_type=None)

        x, y = _tile_for(HUT_LON, HUT_LAT, 9)
        tile = fetch_tile(9, x, y, {"date": TODAY.isoformat(), "cache_ttl": 0})

        props = feature_by_slug(tile, "test-hut")
        assert props is not None
        assert props["d0_status"] == "medium"
        for key in ("d0_type", "d0_type_identifier", "d0_type_color"):
            assert key not in props

    def test_days_max_zoom_clamps_to_one_day(self, hut, hut_types):
        """Below days_max_zoom (default 7) only day 0 is served."""
        open_type, _ = hut_types
        for day in range(4):
            _add_availability(hut, day, free=day, total=10, hut_type=open_type)

        x, y = _tile_for(HUT_LON, HUT_LAT, 6)  # z6 < default 7
        tile = fetch_tile(6, x, y, {"date": TODAY.isoformat(), "cache_ttl": 0})

        props = feature_by_slug(tile, "test-hut")
        assert props is not None
        assert props["days"] == 1  # the clamp is visible to the style
        assert "d0_status" in props
        assert "d1_status" not in props

        # …and the clamp can be disabled per request:
        tile = fetch_tile(
            6, x, y, {"date": TODAY.isoformat(), "days_max_zoom": 0, "cache_ttl": 0}
        )
        props = feature_by_slug(tile, "test-hut")
        assert props is not None
        assert props["days"] == 4
        assert "d3_status" in props

    def test_days_parameter(self, hut, hut_types):
        """days=2 at z9 → exactly two day columns."""
        open_type, _ = hut_types
        for day in range(4):
            _add_availability(hut, day, free=day, total=10, hut_type=open_type)

        x, y = _tile_for(HUT_LON, HUT_LAT, 9)
        tile = fetch_tile(
            9, x, y, {"date": TODAY.isoformat(), "days": 2, "cache_ttl": 0}
        )
        props = feature_by_slug(tile, "test-hut")
        assert props is not None
        assert props["days"] == 2
        assert "d1_status" in props
        assert "d2_status" not in props

    def test_date_window_filters_rows(self, hut, hut_types):
        """Availability outside the requested window is not in the tile."""
        open_type, _ = hut_types
        _add_availability(hut, 3, free=7, total=10, hut_type=open_type)

        x, y = _tile_for(HUT_LON, HUT_LAT, 9)
        # days=2 → the day-3 row falls outside the window → no feature
        tile = fetch_tile(
            9, x, y, {"date": TODAY.isoformat(), "days": 2, "cache_ttl": 0}
        )
        assert feature_by_slug(tile, "test-hut") is None

        # days=4 → included again, at index 3
        tile = fetch_tile(
            9, x, y, {"date": TODAY.isoformat(), "days": 4, "cache_ttl": 0}
        )
        props = feature_by_slug(tile, "test-hut")
        assert props is not None
        assert props["d3_free"] == 7
        assert "d0_free" not in props

    def test_invalid_params_fall_back_to_defaults(self, hut, hut_types):
        """Garbage input never raises (a Martin 500) — defaults apply."""
        open_type, _ = hut_types
        _add_availability(hut, 0, free=1, total=4, hut_type=open_type)

        x, y = _tile_for(HUT_LON, HUT_LAT, 9)
        tile = fetch_tile(9, x, y, {"date": "garbage", "days": "99", "cache_ttl": 0})

        props = feature_by_slug(tile, "test-hut")
        assert props is not None  # default date window (today) matched
        assert props["days"] == 8  # 99 clamped to the 1..8 range
        assert props["d0_free"] == 1

    def test_inactive_or_private_huts_excluded(self, hut, hut_types):
        open_type, _ = hut_types
        _add_availability(hut, 0, free=1, total=4, hut_type=open_type)
        Hut.objects.filter(pk=hut.pk).update(is_public=False)

        x, y = _tile_for(HUT_LON, HUT_LAT, 9)
        tile = fetch_tile(9, x, y, {"date": TODAY.isoformat(), "cache_ttl": 0})
        assert feature_by_slug(tile, "test-hut") is None

    def test_empty_tile(self):
        """A tile with no matching huts returns empty (bytea) bytes."""
        x, y = _tile_for(-30.0, 50.0, 9)  # North Atlantic
        tile = fetch_tile(9, x, y, {"date": TODAY.isoformat(), "cache_ttl": 0})
        assert tile == b""


# ── tile cache ───────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestAvailabilityTileCache:
    def _z9(self) -> tuple[int, int]:
        return _tile_for(HUT_LON, HUT_LAT, 9)

    def test_second_call_hits_cache(self, hut, hut_types):
        open_type, _ = hut_types
        _add_availability(hut, 0, free=5, total=20, hut_type=open_type)

        x, y = self._z9()
        params = {"date": TODAY.isoformat()}
        first = fetch_tile(9, x, y, params)
        second = fetch_tile(9, x, y, params)

        assert first == second
        [row] = AvailabilityTileCache.objects.filter(z=9, x=x, y=y)
        assert row.hits == 1
        assert row.expires_at > timezone.now()

    def test_cache_ttl_zero_bypasses_cache(self, hut, hut_types):
        open_type, _ = hut_types
        _add_availability(hut, 0, free=5, total=20, hut_type=open_type)

        x, y = self._z9()
        fetch_tile(9, x, y, {"date": TODAY.isoformat(), "cache_ttl": 0})
        assert not AvailabilityTileCache.objects.exists()

    def test_different_params_cache_separately(self, hut, hut_types):
        """cache_ttl is not part of the key; days is."""
        open_type, _ = hut_types
        _add_availability(hut, 0, free=5, total=20, hut_type=open_type)
        _add_availability(hut, 1, free=6, total=20, hut_type=open_type)

        x, y = self._z9()
        fetch_tile(9, x, y, {"date": TODAY.isoformat(), "cache_ttl": 60})
        fetch_tile(9, x, y, {"date": TODAY.isoformat(), "cache_ttl": 300})
        fetch_tile(9, x, y, {"date": TODAY.isoformat(), "days": 2, "cache_ttl": 60})

        assert AvailabilityTileCache.objects.count() == 2

    def test_expired_entry_is_regenerated(self, hut, hut_types):
        open_type, _ = hut_types
        _add_availability(hut, 0, free=5, total=20, hut_type=open_type)

        x, y = self._z9()
        params = {"date": TODAY.isoformat()}
        original = fetch_tile(9, x, y, params)

        # expire the cached row
        AvailabilityTileCache.objects.update(
            expires_at=timezone.now() - datetime.timedelta(seconds=1)
        )
        regenerated = fetch_tile(9, x, y, params)

        assert regenerated == original
        [row] = AvailabilityTileCache.objects.filter(z=9, x=x, y=y)
        assert row.expires_at > timezone.now()


@pytest.mark.django_db
def test_cleanup_removes_all_entries(hut, hut_types):
    """cleanup_availability_tile_cache(0) empties the cache table."""
    open_type, _ = hut_types
    _add_availability(hut, 0, free=5, total=20, hut_type=open_type)

    x, y = _tile_for(HUT_LON, HUT_LAT, 9)
    fetch_tile(9, x, y, {"date": TODAY.isoformat()})
    count_before = AvailabilityTileCache.objects.count()
    assert count_before > 0

    with connection.cursor() as cur:
        cur.execute("SELECT cleanup_availability_tile_cache(0)")
        deleted = cur.fetchone()[0]

    assert deleted == count_before
    assert not AvailabilityTileCache.objects.exists()

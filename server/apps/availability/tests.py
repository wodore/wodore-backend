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
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from server.apps.availability.tiles import AvailabilityTileCache
from server.apps.categories.models import Category
from server.apps.geometries.models import GeoPlace
from server.apps.huts.models import Hut
from server.apps.organizations.models import Organization

from .models import (
    GeoPlaceAvailability,
    GeoPlaceAvailabilityHistory,
    GeoPlaceAvailabilityStatus,
    HutAvailability,
)

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
        # hut-level open-type identifier — the accommodation filter's
        # mapProperty (parity with the wd-huts layer features)
        assert props["type_standard_identifier"] == "accommodation.alpinehut-open"
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

    def test_missing_or_invalid_date_returns_empty_tile(self, hut, hut_types):
        """date is required: missing/garbage dates yield empty tiles, not
        a "today" default ("now" logic belongs to the client)."""
        open_type, _ = hut_types
        _add_availability(hut, 0, free=1, total=4, hut_type=open_type)

        x, y = _tile_for(HUT_LON, HUT_LAT, 9)
        for params in (
            {},  # no date at all
            {"date": ""},  # empty
            {"date": "garbage"},  # not a date
            {"date": "21.10.2026"},  # wrong format (European style)
            {"date": "2026-02-30"},  # passes the regex, fails the cast
        ):
            tile = fetch_tile(9, x, y, {**params, "cache_ttl": 0})
            assert tile == b"", f"expected empty tile for {params}"

    def test_days_param_clamped_to_range(self, hut, hut_types):
        """days=99 clamps to 8 — valid date still serves data."""
        open_type, _ = hut_types
        for day in range(8):
            _add_availability(hut, day, free=day, total=10, hut_type=open_type)

        x, y = _tile_for(HUT_LON, HUT_LAT, 9)
        tile = fetch_tile(
            9, x, y, {"date": TODAY.isoformat(), "days": 99, "cache_ttl": 0}
        )

        props = feature_by_slug(tile, "test-hut")
        assert props is not None
        assert props["days"] == 8
        assert "d7_status" in props

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


# ── geoplace availability models (geoplace-availability change, phase A) ──


@pytest.fixture
def place():
    return GeoPlace.objects.create(
        slug="place-1",
        name="Test Place",
        location=Point(HUT_LON, HUT_LAT, srid=4326),
        country_code="CH",
    )


@pytest.fixture
def place_org():
    _reset_pk_sequence(Organization)
    return Organization.objects.create(slug="place-org")


def _place_availability(place, org, day_offset=0, **overrides):
    """Create a GeoPlaceAvailability row with sensible defaults."""
    now = timezone.now()
    defaults = dict(
        geo_place=place,
        source_organization=org,
        source_id="src-1",
        availability_date=TODAY + datetime.timedelta(days=day_offset),
        free=5,
        total=10,
        occupancy_status="medium",
        reservation_status="possible",
        first_checked=now,
        last_checked=now,
    )
    defaults.update(overrides)
    return GeoPlaceAvailability.objects.create(**defaults)


@pytest.mark.django_db
class TestGeoPlaceAvailability:
    def test_single_row_per_place_and_date(self, place, place_org):
        """Spec: one row per place per date — a second row is rejected."""
        _place_availability(place, place_org)
        with pytest.raises(IntegrityError):
            _place_availability(place, place_org)

    def test_invalid_occupancy_status_rejected(self, place, place_org):
        """Spec: check constraints guard the status enums."""
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                _place_availability(place, place_org, occupancy_status="bogus")
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                _place_availability(place, place_org, reservation_status="nope")

    def test_change_detection_records_history_only_on_change(self, place, place_org):
        avail = _place_availability(place, place_org, free=5, total=10)
        hour_ago = timezone.now() - datetime.timedelta(hours=1)

        # Changed values → history row + updated current state
        changed, history = avail.update_availability(
            free=2,
            total=10,
            occupancy_percent=80.0,
            occupancy_status="high",
            reservation_status="possible",
            hut_type=None,
            free_tolerance=0,
        )
        assert changed is True
        assert history is not None and history.free == 2
        avail.refresh_from_db()
        assert avail.free == 2 and avail.occupancy_status == "high"

        # Age both so the no-change path can be observed advancing them;
        # first_checked two hours back also gives duration_seconds meaning
        two_hours_ago = timezone.now() - datetime.timedelta(hours=2)
        history.first_checked = two_hours_ago
        history.last_checked = hour_ago
        history.save(update_fields=["first_checked", "last_checked"])
        avail.last_checked = hour_ago
        avail.save(update_fields=["last_checked"])

        # Unchanged values → no new history row, last_checked advanced
        changed, history2 = avail.update_availability(
            free=2,
            total=10,
            occupancy_percent=80.0,
            occupancy_status="high",
            reservation_status="possible",
            hut_type=None,
            free_tolerance=0,
        )
        assert changed is False and history2 is None
        assert GeoPlaceAvailabilityHistory.objects.count() == 1
        avail.refresh_from_db()
        history.refresh_from_db()
        assert avail.last_checked > hour_ago
        assert history.last_checked > hour_ago
        assert history.duration_seconds >= 7000  # first_checked two hours back

    def test_needing_update_priority_buckets(self, place, place_org):
        two_hours_ago = timezone.now() - datetime.timedelta(hours=2)
        ten_min_ago = timezone.now() - datetime.timedelta(minutes=10)
        # 'full' last checked 2h ago → high priority bucket → included
        _place_availability(
            place,
            place_org,
            day_offset=0,
            occupancy_status="full",
            last_checked=two_hours_ago,
        )
        # 'medium' checked 10 min ago → below medium threshold → excluded
        _place_availability(
            place,
            place_org,
            day_offset=1,
            occupancy_status="medium",
            last_checked=ten_min_ago,
        )
        needing = GeoPlaceAvailability.objects.needing_update(
            high_priority_minutes=30, medium_priority_minutes=180
        )
        assert needing.count() == 1
        assert needing.get().occupancy_status == "full"

    def test_for_date_range_filters(self, place, place_org, hut_types):
        open_type, _ = hut_types
        _place_availability(place, place_org, day_offset=0)
        _place_availability(place, place_org, day_offset=3, hut_type=open_type)
        qs = GeoPlaceAvailability.objects.for_date_range(days=2)
        assert [a.availability_date for a in qs] == [
            TODAY,
        ]
        qs_place = GeoPlaceAvailability.objects.for_date_range(
            place_id=place.id, days=10
        )
        assert qs_place.count() == 2


@pytest.mark.django_db
class TestGeoPlaceAvailabilityStatus:
    def test_mark_success_and_failure_transitions(self, place):
        status = GeoPlaceAvailabilityStatus.objects.create(
            geo_place=place,
            last_checked=timezone.now() - datetime.timedelta(hours=1),
        )
        assert status.has_data is False

        status.mark_failure()
        status.refresh_from_db()
        assert status.consecutive_failures == 1
        assert status.last_success is None

        status.mark_failure()
        status.refresh_from_db()
        assert status.consecutive_failures == 2

        status.mark_success()
        status.refresh_from_db()
        assert status.consecutive_failures == 0
        assert status.has_data is True
        assert status.last_success is not None


@pytest.mark.django_db
class TestGeoPlaceAvailabilityHistory:
    def test_for_trend_orders_out_of_order_inserts(self, place, place_org):
        """Spec: ordering is exclusively first_checked-based — an older row
        inserted after a newer one still sorts correctly."""
        avail = _place_availability(place, place_org)
        now = timezone.now()
        newer = GeoPlaceAvailabilityHistory.objects.create(
            availability=avail,
            geo_place=place,
            availability_date=avail.availability_date,
            free=1,
            total=10,
            occupancy_status="high",
            reservation_status="possible",
            first_checked=now + datetime.timedelta(hours=1),
            last_checked=now + datetime.timedelta(hours=1),
        )
        older = GeoPlaceAvailabilityHistory.objects.create(
            availability=avail,
            geo_place=place,
            availability_date=avail.availability_date,
            free=9,
            total=10,
            occupancy_status="empty",
            reservation_status="possible",
            first_checked=now - datetime.timedelta(hours=1),
            last_checked=now - datetime.timedelta(hours=1),
        )
        trend = list(
            GeoPlaceAvailabilityHistory.objects.for_trend(
                place.id, avail.availability_date, days_before=30
            )
        )
        assert trend == [older, newer]

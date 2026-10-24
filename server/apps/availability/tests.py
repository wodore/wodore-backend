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
from importlib import import_module
from io import StringIO
from types import SimpleNamespace
from typing import Any

import pytest

from django.apps import apps
from django.contrib.gis.geos import Point
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from server.apps.availability.tiles import AvailabilityTileCache
from server.apps.categories.models import Category
from server.apps.geometries.models import GeoPlace, GeoPlaceSourceAssociation
from server.apps.huts.models import Hut
from server.apps.organizations.models import Organization

from .history_move import chunk_ranges, move_chunk, snapshot
from .models import (
    AvailabilityStatus,
    GeoPlaceAvailability,
    GeoPlaceAvailabilityHistory,
    GeoPlaceAvailabilityStatus,
    HutAvailability,
    HutAvailabilityHistory,
)
from .place_dualwrite import mirror_status
from .place_link import (
    WODORE_ORG_SLUG,
    hut_slug_to_place_ids,
    resolve_place,
    unmatched_huts,
)
from .services import AvailabilityService

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
        ).filter(geo_place=place)
        assert needing.count() == 1
        assert needing.get().occupancy_status == "full"

    def test_for_date_range_filters(self, place, place_org, hut_types):
        open_type, _ = hut_types
        _place_availability(place, place_org, day_offset=0)
        _place_availability(place, place_org, day_offset=3, hut_type=open_type)
        qs = GeoPlaceAvailability.objects.for_date_range(place_id=place.id, days=2)
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


# ── phase B: hut→place join, backfill, history move ───────────────────────


@pytest.fixture
def wodore_org():
    # The template-cloned test DB already contains the real wodore org
    _reset_pk_sequence(Organization)
    org, _ = Organization.objects.get_or_create(slug=WODORE_ORG_SLUG)
    return org


def _link(hut, place, wodore_org):
    return GeoPlaceSourceAssociation.objects.create(
        organization=wodore_org, geo_place=place, source_id=hut.slug
    )


def _second_hut(hut_types, slug="other-hut"):
    open_type, closed_type = hut_types
    return Hut.objects.create(
        slug=slug,
        name=f"Test {slug}",
        location=Point(HUT_LON, HUT_LAT, srid=4326),
        is_active=True,
        is_public=True,
        country_field="CH",
        hut_type_open=open_type,
        hut_type_closed=closed_type,
    )


def _hut_history(hut_avail, first_checked, *, free=5):
    return HutAvailabilityHistory.objects.create(
        availability=hut_avail,
        hut=hut_avail.hut,
        availability_date=hut_avail.availability_date,
        free=free,
        total=10,
        free_tolerance=0,
        occupancy_percent=50.0,
        occupancy_status="medium",
        reservation_status="possible",
        first_checked=first_checked,
        last_checked=first_checked + datetime.timedelta(minutes=30),
    )


@pytest.mark.django_db
class TestPlaceLink:
    def test_join_resolution_via_wodore_association(self, hut, place, wodore_org):
        assert hut_slug_to_place_ids() == {}
        assert resolve_place(hut) is None
        _link(hut, place, wodore_org)
        assert hut_slug_to_place_ids() == {hut.slug: place.id}
        assert resolve_place(hut) == place

    def test_unmatched_huts_only_lists_unlinked_with_availability(
        self, hut, hut_types, place, wodore_org
    ):
        open_type, _ = hut_types
        _link(hut, place, wodore_org)
        _add_availability(hut, 0, free=1, total=10, hut_type=open_type)  # linked
        no_data = _second_hut(hut_types, slug="no-data-hut")  # unlinked, no rows
        orphan = _second_hut(hut_types, slug="orphan-hut")  # unlinked with rows
        _add_availability(orphan, 0, free=2, total=10, hut_type=open_type)
        assert list(
            unmatched_huts().filter(slug__in=[hut.slug, no_data.slug, orphan.slug])
        ) == [orphan]
        assert (
            next(iter(unmatched_huts().filter(slug=orphan.slug))).slug == "orphan-hut"
        )
        assert no_data.slug == "no-data-hut"  # sanity: distinct hut


@pytest.mark.django_db
class TestBackfillMigration:
    def _run(self, *, reverse=False):
        mig = import_module(
            "server.apps.availability.migrations.0019_backfill_geoplace_availability"
        )
        (mig.remove_backfill if reverse else mig.backfill)(apps, None)

    def test_field_fidelity_and_status_copy(self, hut, hut_types, place, wodore_org):
        open_type, _ = hut_types
        _link(hut, place, wodore_org)
        src = _add_availability(hut, 0, free=3, total=12, hut_type=open_type)
        src.occupancy_percent = 42.5
        src.occupancy_steps = 40
        src.free_tolerance = 1
        src.save()
        status = AvailabilityStatus.objects.create(
            hut=hut,
            last_checked=timezone.now() - datetime.timedelta(hours=1),
            last_success=timezone.now() - datetime.timedelta(hours=2),
            has_data=True,
            consecutive_failures=3,
        )
        self._run()
        copied = GeoPlaceAvailability.objects.get(
            geo_place=place, availability_date=src.availability_date
        )
        for field in (
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
        ):
            assert getattr(copied, field) == getattr(src, field), field
        st = GeoPlaceAvailabilityStatus.objects.get(geo_place=place)
        for field in (
            "last_checked",
            "last_success",
            "has_data",
            "consecutive_failures",
        ):
            assert getattr(st, field) == getattr(status, field), field

    def test_reverse_restores_empty_state(self, hut, hut_types, place, wodore_org):
        open_type, _ = hut_types
        _link(hut, place, wodore_org)
        _add_availability(hut, 0, free=3, total=12, hut_type=open_type)
        self._run()
        assert GeoPlaceAvailability.objects.exists()
        self._run(reverse=True)
        assert GeoPlaceAvailability.objects.count() == 0
        assert GeoPlaceAvailabilityStatus.objects.count() == 0

    def test_rerun_skips_existing_and_unmatched_stays_out(
        self, hut, hut_types, place, wodore_org
    ):
        open_type, _ = hut_types
        _link(hut, place, wodore_org)
        src = _add_availability(hut, 0, free=3, total=12, hut_type=open_type)
        orphan = _second_hut(hut_types)
        _add_availability(orphan, 0, free=4, total=8, hut_type=open_type)
        self._run()
        self._run()  # rerun must not raise on the unique constraint
        assert GeoPlaceAvailability.objects.filter(geo_place=place).count() == 1
        copied = GeoPlaceAvailability.objects.filter(geo_place=place).first()
        assert copied is not None
        assert copied.source_id == src.source_id


def _setup_move(hut, hut_types, place, place_org, wodore_org):
    """Link hut↔place and seed one hut + one place availability row (TODAY)."""
    open_type, _ = hut_types
    _link(hut, place, wodore_org)
    src = _add_availability(hut, 0, free=3, total=12, hut_type=open_type)
    _place_availability(place, place_org, day_offset=0)
    return src


@pytest.mark.django_db
class TestHistoryMove:
    def test_idempotent_rerun_epoch_cap_and_dry_run(
        self, hut, hut_types, place, place_org, wodore_org
    ):
        src = _setup_move(hut, hut_types, place, place_org, wodore_org)
        lo, _ = snapshot()  # template data below this id is not ours
        _hut_history(src, timezone.now() - datetime.timedelta(hours=2), free=8)
        _hut_history(src, timezone.now() - datetime.timedelta(hours=1), free=5)
        future = _hut_history(
            src, timezone.now() + datetime.timedelta(minutes=5), free=1
        )
        hi, started_at = snapshot()
        assert hi == future.id

        stats = move_chunk(lo, hi, started_at)
        assert stats["moved"] == 2  # epoch cap excludes `future`
        rows = list(
            GeoPlaceAvailabilityHistory.objects.for_trend(
                place.id, src.availability_date, days_before=7
            )
        )
        assert [r.free for r in rows] == [8, 5]  # first_checked ascending
        assert all(r.availability_id is not None for r in rows)

        stats2 = move_chunk(lo, hi, started_at)
        assert stats2["moved"] == 0
        assert stats2["skipped_existing"] == 2

        extra = _hut_history(src, timezone.now() - datetime.timedelta(hours=3), free=9)
        stats3 = move_chunk(lo, hi + 100, started_at, dry_run=True)
        assert stats3["moved"] == 1  # only `extra` is new in the wider range
        assert stats3["skipped_existing"] == 2
        assert GeoPlaceAvailabilityHistory.objects.count() == 2
        assert extra.free == 9  # sanity

    def test_unmatched_and_missing_availability_counters(
        self, hut, hut_types, place, place_org, wodore_org
    ):
        open_type, _ = hut_types
        orphan = _second_hut(hut_types)
        orphan_src = _add_availability(orphan, 0, free=4, total=8, hut_type=open_type)
        # Linked hut, but history date has no place availability row
        _link(hut, place, wodore_org)
        hut_src = _add_availability(hut, 2, free=3, total=12, hut_type=open_type)
        # place availability exists only for TODAY (offset 0), not offset 2
        _place_availability(place, place_org, day_offset=0)
        lo, _ = snapshot()
        orphan_hist = _hut_history(
            orphan_src, timezone.now() - datetime.timedelta(hours=1), free=6
        )
        hut_hist = _hut_history(
            hut_src, timezone.now() - datetime.timedelta(hours=1), free=2
        )
        hi, started_at = snapshot()

        stats = move_chunk(lo, hi, started_at)
        assert sorted(stats["unmatched"]) == [orphan.slug]
        assert stats["moved"] == 1
        assert stats["availability_missing"] == 1
        moved_row = GeoPlaceAvailabilityHistory.objects.get(
            availability_date=hut_src.availability_date
        )
        assert moved_row.availability_id is None
        assert moved_row.geo_place == place
        assert orphan_hist.free == 6  # sanity: source row untouched
        assert hut_hist.pk is not None

    def test_chunk_ranges(self):
        assert chunk_ranges(0, 10) == []
        assert chunk_ranges(5, 2) == [(0, 2), (2, 4), (4, 5)]
        assert chunk_ranges(4, 10) == [(0, 4)]


@pytest.mark.django_db
class TestPhaseBCommands:
    def test_move_command_sync_resumes_after_partial(
        self, hut, hut_types, place, place_org, wodore_org
    ):
        src = _setup_move(hut, hut_types, place, place_org, wodore_org)
        lo, _ = snapshot()
        h1 = _hut_history(src, timezone.now() - datetime.timedelta(hours=3), free=9)
        _hut_history(src, timezone.now() - datetime.timedelta(hours=2), free=8)
        _hut_history(src, timezone.now() - datetime.timedelta(hours=1), free=7)
        hi, started_at = snapshot()

        # Simulate an interrupted run: only the first chunk completed
        first = move_chunk(lo, h1.id, started_at)
        assert first["moved"] == 1

        buf = StringIO()
        call_command(
            "move_availability_history",
            "--sync",
            "--batch-size",
            "1",
            "--min-id",
            str(lo),
            "--max-id",
            str(hi),
            stdout=buf,
        )
        out = buf.getvalue()
        assert "Done: moved=2" in out
        place_rows = GeoPlaceAvailabilityHistory.objects.filter(geo_place=place)
        assert place_rows.count() == 3
        # natural-key integrity: no duplicates after resume
        keys = list(
            place_rows.values_list("geo_place_id", "availability_date", "first_checked")
        )
        assert len(keys) == len(set(keys))

    def test_report_command_gate_states(self, hut, hut_types, place, wodore_org):
        open_type, _ = hut_types
        _link(hut, place, wodore_org)
        _add_availability(hut, 0, free=3, total=12, hut_type=open_type)
        buf = StringIO()
        call_command("report_unmatched_huts", stdout=buf)
        assert hut.slug not in buf.getvalue()  # linked huts are never listed

        orphan = _second_hut(hut_types)
        _add_availability(orphan, 0, free=4, total=8, hut_type=open_type)
        buf2 = StringIO()
        call_command("report_unmatched_huts", stdout=buf2)
        out = buf2.getvalue()
        assert orphan.slug in out
        assert "gate: NOT empty" in out


# ── phase C: dual-write + place-driven cadence ───────────────────────────


def _fake_booking(
    date,
    *,
    free=5,
    total=10,
    hut_type=None,
    status="medium",
    reservation="possible",
    link="",
):
    return SimpleNamespace(
        date=date,
        free=free,
        total=total,
        free_tolerance=0,
        occupancy_percent=50.0,
        occupancy_steps=50,
        occupancy_status=status,
        reservation_status=reservation,
        link=link,
        hut_type=hut_type,
    )


def _fake_hut_booking(hut, bookings, source):
    return SimpleNamespace(
        slug=hut.slug, source=source, source_id="src-1", bookings=bookings
    )


def _seed_both_sides(hut, place, place_org, *, free=5, total=10):
    """Seed matching current-state rows on both sides for TODAY."""
    aged = timezone.now() - datetime.timedelta(hours=2)
    hut_avail = HutAvailability.objects.create(
        hut=hut,
        source_organization=place_org,
        source_id="src-1",
        availability_date=TODAY,
        free=free,
        total=total,
        free_tolerance=0,
        occupancy_percent=50.0,
        occupancy_steps=50,
        occupancy_status="medium",
        reservation_status="possible",
        link="",
        hut_type=None,
        first_checked=aged,
        last_checked=aged,
    )
    place_avail = GeoPlaceAvailability.objects.create(
        geo_place=place,
        source_organization=place_org,
        source_id="src-1",
        availability_date=TODAY,
        free=free,
        total=total,
        free_tolerance=0,
        occupancy_percent=50.0,
        occupancy_steps=50,
        occupancy_status="medium",
        reservation_status="possible",
        link="",
        hut_type=None,
        first_checked=aged,
        last_checked=aged,
    )
    return hut_avail, place_avail


@pytest.mark.django_db
class TestDualWrite:
    def test_batch_writes_both_sides_identically(
        self, hut, hut_types, place, place_org, wodore_org
    ):
        _link(hut, place, wodore_org)
        hut_avail, place_avail = _seed_both_sides(hut, place, place_org)
        now = timezone.now()
        tomorrow = TODAY + datetime.timedelta(days=1)
        batch = [
            (
                hut,
                _fake_hut_booking(
                    hut,
                    [
                        _fake_booking(TODAY, free=2),  # changed
                        _fake_booking(tomorrow, free=7, total=12),  # new date
                    ],
                    source=place_org.slug,
                ),
            )
        ]
        results = AvailabilityService._process_huts_batch(
            batch=batch, now=now, update_history_last_checked=True
        )
        assert results[0].success
        assert results[0].records_created == 1
        assert results[0].records_updated == 1

        hut_avail.refresh_from_db()
        place_avail.refresh_from_db()
        assert hut_avail.free == 2 and place_avail.free == 2
        assert hut_avail.last_checked == now
        assert place_avail.last_checked == now
        assert place_avail.first_checked == hut_avail.first_checked

        new_hut = HutAvailability.objects.get(hut=hut, availability_date=tomorrow)
        new_place = GeoPlaceAvailability.objects.get(
            geo_place=place, availability_date=tomorrow
        )
        for field in (
            "free",
            "total",
            "occupancy_percent",
            "occupancy_status",
            "reservation_status",
            "first_checked",
            "last_checked",
        ):
            assert getattr(new_place, field) == getattr(new_hut, field), field

        # change event + initial entry for the created row — on both sides
        assert HutAvailabilityHistory.objects.filter(hut=hut).count() == 2
        assert GeoPlaceAvailabilityHistory.objects.filter(geo_place=place).count() == 2
        hh = HutAvailabilityHistory.objects.get(hut=hut, availability_date=TODAY)
        ph = GeoPlaceAvailabilityHistory.objects.get(
            geo_place=place, availability_date=TODAY
        )
        for field in (
            "free",
            "total",
            "occupancy_percent",
            "occupancy_status",
            "first_checked",
            "last_checked",
        ):
            assert getattr(ph, field) == getattr(hh, field), field

    def test_unchanged_run_advances_last_checked_both_sides(
        self, hut, hut_types, place, place_org, wodore_org
    ):
        _link(hut, place, wodore_org)
        hut_avail, place_avail = _seed_both_sides(hut, place, place_org)
        aged = timezone.now() - datetime.timedelta(hours=3)
        hh = HutAvailabilityHistory.objects.create(
            availability=hut_avail,
            hut=hut,
            availability_date=TODAY,
            free=5,
            total=10,
            free_tolerance=0,
            occupancy_percent=50.0,
            occupancy_status="medium",
            reservation_status="possible",
            first_checked=aged,
            last_checked=aged,
        )
        ph = GeoPlaceAvailabilityHistory.objects.create(
            availability=place_avail,
            geo_place=place,
            availability_date=TODAY,
            free=5,
            total=10,
            free_tolerance=0,
            occupancy_percent=50.0,
            occupancy_status="medium",
            reservation_status="possible",
            first_checked=aged,
            last_checked=aged,
        )
        now = timezone.now()
        batch = [
            (
                hut,
                _fake_hut_booking(hut, [_fake_booking(TODAY)], source=place_org.slug),
            )
        ]
        AvailabilityService._process_huts_batch(
            batch=batch, now=now, update_history_last_checked=True
        )
        hut_avail.refresh_from_db()
        place_avail.refresh_from_db()
        assert hut_avail.last_checked == now
        assert place_avail.last_checked == now
        hh.refresh_from_db()
        ph.refresh_from_db()
        assert hh.last_checked == now
        assert ph.last_checked == now
        assert HutAvailabilityHistory.objects.filter(hut=hut).count() == 1
        assert GeoPlaceAvailabilityHistory.objects.filter(geo_place=place).count() == 1

    def test_unmatched_hut_writes_hut_side_only(self, hut, hut_types, place_org):
        before = GeoPlaceAvailability.objects.count()
        now = timezone.now()
        tomorrow = TODAY + datetime.timedelta(days=1)
        batch = [
            (
                hut,
                _fake_hut_booking(
                    hut, [_fake_booking(tomorrow)], source=place_org.slug
                ),
            )
        ]
        results = AvailabilityService._process_huts_batch(batch=batch, now=now)
        assert results[0].success
        assert HutAvailability.objects.filter(hut=hut).count() == 1
        assert GeoPlaceAvailability.objects.count() == before  # place side skipped

    def test_mirror_status_lifecycle(self, hut, place, wodore_org):
        _link(hut, place, wodore_org)
        t1 = timezone.now()
        mirror_status([hut], [], t1)
        st = GeoPlaceAvailabilityStatus.objects.get(geo_place=place)
        assert st.has_data is True
        assert st.last_success == t1
        assert st.consecutive_failures == 0

        t2 = t1 + datetime.timedelta(minutes=1)
        mirror_status([], [hut], t2)
        st.refresh_from_db()
        assert st.consecutive_failures == 1

        t3 = t1 + datetime.timedelta(minutes=2)
        mirror_status([hut], [], t3)
        st.refresh_from_db()
        assert st.consecutive_failures == 0
        assert st.last_success == t3


@pytest.mark.django_db
class TestPlaceDrivenCadence:
    def test_discovery_covers_all_three_branches(
        self, hut, hut_types, place, place_org, wodore_org
    ):
        # Branch 1: linked hut with a stale high-priority place row
        _link(hut, place, wodore_org)
        Hut.objects.filter(pk=hut.pk).update(availability_source_ref=place_org)
        aged = timezone.now() - datetime.timedelta(hours=2)
        GeoPlaceAvailability.objects.create(
            geo_place=place,
            source_organization=place_org,
            source_id="src-1",
            availability_date=TODAY,
            free=0,
            total=10,
            occupancy_status="full",
            reservation_status="possible",
            first_checked=aged,
            last_checked=aged,
        )

        # Branch 2: linked hut whose place status is stale
        place2 = GeoPlace.objects.create(
            slug="place-2",
            name="Place Two",
            location=Point(HUT_LON, HUT_LAT, srid=4326),
            country_code="CH",
        )
        hut_b = _second_hut(hut_types, slug="stale-status-hut")
        _link(hut_b, place2, wodore_org)
        Hut.objects.filter(pk=hut_b.pk).update(availability_source_ref=place_org)
        GeoPlaceAvailabilityStatus.objects.create(
            geo_place=place2,
            last_checked=timezone.now() - datetime.timedelta(days=8),
        )

        # Branch 3: unmatched hut with a source but no place status
        hut_c = _second_hut(hut_types, slug="unmatched-new-hut")
        Hut.objects.filter(pk=hut_c.pk).update(availability_source_ref=place_org)

        huts = GeoPlaceAvailability.objects.get_huts_needing_update(
            high_priority_minutes=30, medium_priority_minutes=180
        )
        slugs = set(huts.values_list("slug", flat=True))
        # dev-data subset assertions (template rows also match the branches)
        assert {"test-hut", "stale-status-hut", "unmatched-new-hut"} <= slugs

"""The restored clustered ``get_geoplaces_for_tiles`` function contract.

Migration ``0076_restore_clustered_geoplaces_tiles`` re-based the
function on the 0041 clustered shape (0068 had rebuilt it from 0028's
pre-clustering template). These tests pin the RESTORED contract:

* flat category properties (``category_slug``/``category_identifier``/
  ``category_order``/``color``/``parent_color``/``parent_slug``) — and
  NO flattened jsonb-object keys (ST_AsMVT flattens jsonb objects into
  top-level keys, which shadowed ``name``/``slug``/``color``);
* server-side clustering (``count``) at low zooms, raw features above
  the transition zone;
* ``category_tree`` subtree filtering (kind/group/domain ancestor
  match) — the OSM importer links leaf categories only, group-level
  overlay filters rely on this;
* comma-separated ``categories``/``categories_all`` values (the
  0028-era ``::text[]`` cast rejected plain ``a,b`` strings);
* the DB tile cache round trip.

Tiles are decoded with a compact in-test MVT parser (protobuf wire
format) — no decoder dependency exists in the project.
"""

from __future__ import annotations

import json
import math
import struct
from collections.abc import Iterator
from typing import Any

import pytest

from django.contrib.gis.geos import Point
from django.db import connection

from server.apps.categories.models import Category
from server.apps.geometries.models import GeoPlace

pytestmark = pytest.mark.django_db

#: Zurich-ish coordinates for tile math (dense enough to be realistic,
#: arbitrary enough to avoid colliding with seed data tiles).
LON, LAT = 8.55, 47.03


# ── minimal MVT decoder (protobuf wire format) ───────────────────────


def _varint(buf: bytes, pos: int) -> tuple[int, int]:
    result = shift = 0
    while True:
        byte = buf[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7


def _fields(buf: bytes) -> Iterator[tuple[int, int, Any]]:
    """Yield ``(field, wire_type, value)`` protobuf triples.

    ``value`` is ``bytes`` for length-delimited fields (wire types 2/1/5)
    and ``int`` for varints — the union is inherent to the wire format,
    consumers branch on ``wire_type`` (hence ``Any`` in the signature).
    """
    pos = 0
    while pos < len(buf):
        key, pos = _varint(buf, pos)
        field, wtype = key >> 3, key & 7
        value: Any
        if wtype == 0:
            value, pos = _varint(buf, pos)
        elif wtype == 2:
            length, pos = _varint(buf, pos)
            value = buf[pos : pos + length]
            pos += length
        elif wtype == 5:
            value = buf[pos : pos + 4]
            pos += 4
        elif wtype == 1:
            value = buf[pos : pos + 8]
            pos += 8
        else:
            msg = f"unsupported wire type {wtype}"
            raise ValueError(msg)
        yield field, wtype, value


def decode_mvt(tile: bytes) -> list[dict[str, Any]]:
    """Feature property dicts of every layer in the tile."""
    features: list[dict[str, Any]] = []
    for field, wtype, value in _fields(tile):
        if field != 3 or wtype != 2:
            continue
        keys: list[str] = []
        values: list[Any] = []
        rows: list[list[int]] = []
        for lf, lwt, lval in _fields(value):
            if lf == 3 and lwt == 2:
                keys.append(lval.decode())
            elif lf == 4 and lwt == 2:
                for vf, vwt, vval in _fields(lval):
                    if vf == 1 and vwt == 2:
                        values.append(vval.decode("utf-8", "replace"))
                    elif vf == 2 and vwt == 5:
                        values.append(struct.unpack("<f", vval)[0])
                    elif vf == 3 and vwt == 1:
                        values.append(struct.unpack("<d", vval)[0])
                    elif vwt == 0:
                        values.append(bool(vval) if vf == 7 else vval)
            elif lf == 2 and lwt == 2:
                tags: list[int] = []
                for ff, fwt, fval in _fields(lval):
                    if ff == 2 and fwt == 2:
                        pos = 0
                        while pos < len(fval):
                            tag, pos = _varint(fval, pos)
                            tags.append(tag)
                rows.append(tags)
        for tags in rows:
            props = {
                keys[tags[i]]: values[tags[i + 1]] for i in range(0, len(tags) - 1, 2)
            }
            features.append(props)
    return features


# ── helpers ──────────────────────────────────────────────────────────


def _tile_xy(lon: float, lat: float, zoom: int) -> tuple[int, int]:
    n = 1 << zoom
    x = math.floor((lon + 180) / 360 * n)
    lat_rad = math.radians(lat)
    y = math.floor(
        (1 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi) / 2 * n
    )
    return x, y


def _fetch(zoom: int, params: dict[str, Any]) -> list[dict[str, Any]]:
    x, y = _tile_xy(LON, LAT, zoom)
    query = "SELECT get_geoplaces_for_tiles(%s, %s, %s, %s::jsonb)"
    with connection.cursor() as cursor:
        cursor.execute(query, [zoom, x, y, json.dumps(params)])
        tile = cursor.fetchone()[0]
    if not tile:
        return []
    return decode_mvt(bytes(tile))


def _category(slug: str, parent: Category | None = None, **kwargs: Any) -> Category:
    cat, _ = Category.objects.get_or_create(
        slug=slug,
        parent=parent,
        defaults={"name": slug, "color": kwargs.pop("color", "#111111"), **kwargs},
    )
    return cat


@pytest.fixture(autouse=True)
def _clean_tile_cache() -> None:
    """Tile-cache rows must never leak between tests (7-day TTL)."""
    with connection.cursor() as cursor:
        cursor.execute("TRUNCATE geometries_tile_cache")


@pytest.fixture
def poi_tree() -> dict[str, Category]:
    """A small place/category setup around the accommodation group.

    amenity (super-root, from migrations) → test groups → kinds; places
    link LEAF categories only (importer parity).
    """
    amenity = Category.objects.filter(slug="amenity", parent__slug="map").first()
    if amenity is None:
        amenity = _category("amenity")
    group = _category("accommodation", parent=amenity, color="#224E3B")
    hut = _category("hut", parent=group, color="#abcdef")
    hotel = _category("hotel", parent=group, color="#987654")
    viewpoint = _category("panorama-spot", parent=amenity, color="#4B8E43")

    def place(
        name: str,
        lat_offset: float,
        category: Category,
        importance: int,
        elevation: int | None = None,
    ) -> GeoPlace:
        place = GeoPlace.objects.create(
            name=name,
            location=Point(LON, LAT + lat_offset, srid=4326),
            country_code="CH",
            importance=importance,
            elevation=elevation,
            is_active=True,
            is_public=True,
        )
        place.categories.add(category)
        return place

    # three co-located huts (one cluster), a hotel and a viewpoint;
    # Clusterhutte B keeps elevation NULL (absent-property semantics)
    place("Clusterhutte A", 0.0000, hut, 30, elevation=2200)
    place("Clusterhutte B", 0.0001, hut, 20)
    place("Clusterhutte C", 0.0002, hut, 10, elevation=2100)
    place("Grand Hotel", 0.0001, hotel, 40, elevation=1800)
    place("Aussichtspunkt", 0.0000, viewpoint, 50, elevation=900)
    # viewpoint key maps to the seed-collision-safe slug panorama-spot
    return {"group": group, "hut": hut, "hotel": hotel, "viewpoint": viewpoint}


# ── tests ────────────────────────────────────────────────────────────


class TestRawPath:
    # setup-only fixture: requested via usefixtures, the parameter
    # stays only where the tree dict itself is referenced
    pytestmark = pytest.mark.usefixtures("poi_tree")

    def test_flat_category_props(self, poi_tree: dict[str, Category]) -> None:
        features = _fetch(14, {"lang": "de", "cache_ttl_days": 0})
        by_name = {f.get("name"): f for f in features}
        hut_feature = by_name["Clusterhutte A"]
        assert hut_feature["count"] == 1
        assert hut_feature["category_slug"] == "hut"
        assert hut_feature["category_identifier"] == "accommodation.hut"
        assert hut_feature["category_order"] == poi_tree["hut"].order
        assert hut_feature["color"] == poi_tree["hut"].color
        assert hut_feature["parent_slug"] == "accommodation"
        assert hut_feature["parent_color"] == poi_tree["group"].color
        assert hut_feature["slug"]

    def test_no_flattened_category_object_keys(self) -> None:
        """The 0041 ``category`` jsonb object flattened into top-level
        keys (order/identifier/name shadowing the real columns)."""
        features = _fetch(14, {"lang": "de", "cache_ttl_days": 0})
        all_keys: set[str] = set()
        for feature in features:
            all_keys.update(feature)
        assert "order" not in all_keys
        assert "identifier" not in all_keys

    def test_names_gated_by_max_label_zoom(self) -> None:
        features = _fetch(14, {"lang": "de", "max_label_zoom": 15, "cache_ttl_days": 0})
        assert features
        # below the label gate names are EMPTY STRINGS, not absent
        # (ST_AsMVT keeps '' as a present-but-empty property)
        assert all(not f.get("name") for f in features)


class TestClusterPath:
    pytestmark = pytest.mark.usefixtures("poi_tree")

    def test_clusters_carry_count(self) -> None:
        features = _fetch(5, {"lang": "de", "cache_ttl_days": 0})
        assert features
        huts = [f for f in features if f.get("category_slug") == "hut"]
        assert huts, "the three co-located huts must appear"
        assert max(f["count"] for f in huts) == 3
        # cluster zone carries no identity (empty strings, not NULL —
        # ST_AsMVT keeps empty strings as present-but-empty props)
        assert all(not f.get("name") for f in features)
        assert all(not f.get("slug") for f in features)

    def test_high_zoom_returns_raw_features(self) -> None:
        features = _fetch(14, {"lang": "de", "cache_ttl_days": 0})
        assert features
        assert all(f["count"] == 1 for f in features)


class TestElevationField:
    """``elevation`` is opt-in via ``fields`` (migration 0077)."""

    pytestmark = pytest.mark.usefixtures("poi_tree")

    ELEVATION_FIELDS = "color,importance,count,name,slug,elevation"

    def test_raw_features_carry_elevation_when_requested(self) -> None:
        features = _fetch(
            14, {"lang": "de", "fields": self.ELEVATION_FIELDS, "cache_ttl_days": 0}
        )
        by_name = {f.get("name"): f for f in features}
        assert by_name["Clusterhutte A"]["elevation"] == 2200
        assert by_name["Aussichtspunkt"]["elevation"] == 900
        # NULL elevation (Clusterhutte B) is OMITTED, not zero
        assert "elevation" not in by_name["Clusterhutte B"]

    def test_elevation_absent_when_not_requested(self) -> None:
        """Non-opting consumers' tiles stay byte-identical."""
        features = _fetch(14, {"lang": "de", "cache_ttl_days": 0})
        assert features
        assert all("elevation" not in f for f in features)

    def test_cluster_features_never_carry_elevation(self) -> None:
        features = _fetch(
            5, {"lang": "de", "fields": self.ELEVATION_FIELDS, "cache_ttl_days": 0}
        )
        assert features
        # cluster zone: every feature is a cluster feature (count > 1
        # or a singleton cell) — none carries elevation
        assert all("elevation" not in f for f in features)

    def test_transition_individuals_carry_elevation(self) -> None:
        """The clustered path's raw twin (graduated individuals) opts
        into elevation like the full raw path does."""
        features = _fetch(
            8,
            {
                "lang": "de",
                "fields": self.ELEVATION_FIELDS,
                "cluster_max_zoom": 7,
                "cache_ttl_days": 0,
            },
        )
        viewpoint = [f for f in features if f.get("category_slug") == "panorama-spot"]
        assert len(viewpoint) == 1
        assert viewpoint[0]["count"] == 1
        assert viewpoint[0]["elevation"] == 900


class TestTransitionIdentity:
    """Graduated individuals in the transition zone carry real
    identity (migration 0077 fixed the ''-slug/name twin)."""

    pytestmark = pytest.mark.usefixtures("poi_tree")

    def test_transition_individuals_carry_slug(self) -> None:
        # cluster_max_zoom=7 → z8/z9 transition; the viewpoint
        # (importance 50 >= default threshold) graduates raw at z8
        features = _fetch(8, {"lang": "de", "cluster_max_zoom": 7, "cache_ttl_days": 0})
        viewpoint = [f for f in features if f.get("category_slug") == "panorama-spot"]
        assert len(viewpoint) == 1
        assert viewpoint[0]["slug"], "graduated individuals need a real slug"
        # below the default max_label_zoom (14) names stay gated
        assert not viewpoint[0]["name"]

    def test_transition_names_at_label_zoom(self) -> None:
        features = _fetch(
            8,
            {
                "lang": "de",
                "cluster_max_zoom": 7,
                "max_label_zoom": 8,
                "cache_ttl_days": 0,
            },
        )
        viewpoint = [f for f in features if f.get("category_slug") == "panorama-spot"]
        assert viewpoint[0]["name"] == "Aussichtspunkt"
        assert viewpoint[0]["slug"]

    def test_full_clustering_zone_stays_anonymous(self) -> None:
        """Cluster features (including singleton cells) keep ''
        identity — members resolve via the nearby endpoint on click."""
        features = _fetch(8, {"lang": "de", "cluster_max_zoom": 7, "cache_ttl_days": 0})
        # the hotel (importance 40 < 50) still clusters at z8 — even
        # as a singleton cell it carries no identity
        hotel = [f for f in features if f.get("category_slug") == "hotel"]
        assert len(hotel) == 1
        assert hotel[0]["count"] == 1
        assert not hotel[0]["slug"]
        assert not hotel[0]["name"]


class TestCategoryFilters:
    pytestmark = pytest.mark.usefixtures("poi_tree")

    def test_category_tree_matches_group(self) -> None:
        features = _fetch(
            14, {"lang": "de", "category_tree": "accommodation", "cache_ttl_days": 0}
        )
        assert {f["category_slug"] for f in features} == {"hut", "hotel"}

    def test_category_tree_matches_domain(self) -> None:
        features = _fetch(
            14, {"lang": "de", "category_tree": "amenity", "cache_ttl_days": 0}
        )
        assert {f["category_slug"] for f in features} == {
            "hut",
            "hotel",
            "panorama-spot",
        }

    def test_category_tree_unknown_slug_is_empty(self) -> None:
        features = _fetch(
            14, {"lang": "de", "category_tree": "does_not_exist", "cache_ttl_days": 0}
        )
        assert features == []

    def test_comma_separated_categories_or(self) -> None:
        """Plain ``a,b`` values must parse (the 0028-era ``::text[]``
        cast rejected them)."""
        features = _fetch(
            14,
            {"lang": "de", "categories": "hut,hotel", "cache_ttl_days": 0},
        )
        assert {f["category_slug"] for f in features} == {"hut", "hotel"}

    def test_categories_all_requires_every_slug(self) -> None:
        features = _fetch(
            14,
            {"lang": "de", "categories_all": "hut,hotel", "cache_ttl_days": 0},
        )
        # no single place links both hut and hotel
        assert features == []


class TestTileCache:
    pytestmark = pytest.mark.usefixtures("poi_tree")

    def test_tile_cached_and_served(self) -> None:
        first = _fetch(5, {"lang": "de", "cache_ttl_days": 1})
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM geometries_tile_cache")
            assert cursor.fetchone()[0] >= 1
        second = _fetch(5, {"lang": "de", "cache_ttl_days": 1})
        assert len(first) == len(second)

    def test_zero_ttl_never_persists(self) -> None:
        _fetch(5, {"lang": "de", "cache_ttl_days": 0})
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM geometries_tile_cache")
            assert cursor.fetchone()[0] == 0

"""The geoplaces near endpoint + the tiles/near sync invariant.

``GET /v1/geoplaces/near`` (cluster members / proximity, see
``server/apps/geometries/api_near.py``) and the hard invariant from
openspec ``add-geoplaces-near``: every server-side cluster feature's
``count`` MUST equal the near endpoint's ``count`` for its anchor at
the tile's zoom — both sides read the shared
``geoplaces_cluster_membership`` helper, and this test fails the
moment either side drifts.
"""

from __future__ import annotations

import json
import math
import struct
from typing import Any

import pytest

from django.contrib.gis.geos import Point
from django.test import Client

from server.apps.categories.models import Category
from server.apps.geometries.models import GeoPlace

from .test_geoplaces_tile_function import LAT, LON, _tile_xy, _varint

pytestmark = pytest.mark.django_db

NEAR_URL = "/v1/geoplaces/near"


# ── tile helpers (geometry-aware) ────────────────────────────────────


def _tile_features(z: int, params: dict[str, Any]) -> list[dict[str, Any]]:
    """Tile features with geometry: decode one point per feature.

    Reuses the wire-format varint parser from the tile-function tests;
    additionally walks each feature's geometry (field 4) collecting its
    coordinate pairs (zigzag deltas, 4096-extent tile space).
    """
    from django.db import connection

    x, y = _tile_xy(LON, LAT, z)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT get_geoplaces_for_tiles(%s, %s, %s, %s::jsonb)",
            [z, x, y, json.dumps(params)],
        )
        tile = bytes(cursor.fetchone()[0])

    features: list[dict[str, Any]] = []
    for field, wtype, value in _iter_fields(tile):
        if field != 3 or wtype != 2:
            continue  # layer
        for lf, lwt, lval in _iter_fields(value):
            if lf != 2 or lwt != 2:
                continue  # feature
            props: dict[str, Any] = {}
            geom: list[tuple[int, int]] = []
            for ff, fwt, fval in _iter_fields(lval):
                if ff == 2 and fwt == 2:  # tags → props
                    props.update(_decode_tags(value, fval))
                elif ff == 4 and fwt == 2:  # geometry
                    geom = _decode_point_geometry(fval)
            features.append({"props": props, "geom": geom, "z": z, "x": x, "y": y})
    return features


def _iter_fields(buf: bytes) -> Any:
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
        else:
            msg = f"unsupported wire type {wtype}"
            raise ValueError(msg)
        yield field, wtype, value


def _decode_tags(layer: bytes, tags_buf: bytes) -> dict[str, Any]:
    """Feature tags against the layer's key/value tables."""
    keys: list[str] = []
    values: list[Any] = []
    for lf, lwt, lval in _iter_fields(layer):
        if lf == 3 and lwt == 2:
            keys.append(lval.decode())
        elif lf == 4 and lwt == 2:
            for vf, vwt, vval in _iter_fields(lval):
                if vf == 1 and vwt == 2:
                    values.append(vval.decode("utf-8", "replace"))
                elif vf == 2 and vwt == 5:
                    values.append(struct.unpack("<f", vval)[0])
                elif vf == 3 and vwt == 1:
                    values.append(struct.unpack("<d", vval)[0])
                elif vwt == 0:
                    values.append(bool(vval) if vf == 7 else vval)
    pos = 0
    tag_ids: list[int] = []
    while pos < len(tags_buf):
        tag, pos = _varint(tags_buf, pos)
        tag_ids.append(tag)
    return {
        keys[tag_ids[i]]: values[tag_ids[i + 1]] for i in range(0, len(tag_ids) - 1, 2)
    }


def _decode_point_geometry(geom: bytes) -> list[tuple[int, int]]:
    """Decode MVT geometry commands into absolute tile coords."""
    points: list[tuple[int, int]] = []
    pos = 0
    cx = cy = 0
    while pos < len(geom):
        command, pos = _varint(geom, pos)
        cmd_id, count = command & 0x7, command >> 3
        for _ in range(count):
            dx, pos = _varint(geom, pos)
            dy, pos = _varint(geom, pos)
            if cmd_id == 1:  # MoveTo
                cx += (dx >> 1) ^ -(dx & 1)
                cy += (dy >> 1) ^ -(dy & 1)
                points.append((cx, cy))
            else:  # LineTo segments — first point already recorded
                cx += (dx >> 1) ^ -(dx & 1)
                cy += (dy >> 1) ^ -(dy & 1)
    return points


def _to_lnglat(feature: dict[str, Any]) -> tuple[float, float]:
    """First geometry point → (lon, lat) — the feature's anchor."""
    x, y = feature["geom"][0]
    z, tx, ty = feature["z"], feature["x"], feature["y"]
    n = 1 << z
    lon = (tx + x / 4096) / n * 360 - 180
    v = (ty + y / 4096) / n
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * v))))
    return lon, lat


# ── fixture ─────────────────────────────────────────────────────────


@pytest.fixture
def amenity_poi_field() -> dict[str, Any]:
    """A dense field of places around one anchor: enough huts to exceed
    the endpoint's limit cap, hotels to share the cell with a different
    category, a high-importance viewpoint that graduates raw in every
    transition band, and a far-away outlier outside every grid."""
    amenity = Category.objects.filter(slug="amenity", parent__slug="map").first()
    if amenity is None:
        amenity = Category.objects.create(slug="amenity", name="amenity")
    group = Category.objects.get_or_create(
        slug="accommodation",
        parent=amenity,
        defaults={"name": "acc", "color": "#111111"},
    )[0]
    hut = Category.objects.get_or_create(
        slug="hut", parent=group, defaults={"name": "hut", "color": "#abcdef"}
    )[0]
    hotel = Category.objects.get_or_create(
        slug="hotel", parent=group, defaults={"name": "hotel", "color": "#987654"}
    )[0]
    viewpoint = Category.objects.get_or_create(
        slug="panorama-spot",
        parent=amenity,
        defaults={"name": "panorama", "color": "#4B8E43"},
    )[0]

    def place(
        name: str, lat_offset: float, category: Category, importance: int
    ) -> GeoPlace:
        place = GeoPlace.objects.create(
            name=name,
            location=Point(LON, LAT + lat_offset, srid=4326),
            country_code="CH",
            importance=importance,
            elevation=2000 + len(name),
            is_active=True,
            is_public=True,
        )
        place.categories.add(category)
        return place

    # 30 huts in one tight blob (limit cap is 25 — count > data length)
    for i in range(30):
        place(f"Clusterhutte {i:02d}", 0.0000 + i * 0.00002, hut, 10 + i)
    # hotels in the same cells, different category
    place("Grand Hotel", 0.0003, hotel, 40)
    place("Hotel Zweiti", 0.0004, hotel, 35)
    # graduates raw in every transition band (importance >= 50)
    viewpoint_place = place("Aussichtspunkt", 0.0001, viewpoint, 50)
    # far away — outside any anchor cell, must never leak into members
    outlier = place("Einsame Huette", 0.5, hut, 99)
    return {
        "group": group,
        "hut": hut,
        "hotel": hotel,
        # viewpoint maps to the seed-collision-safe slug panorama-spot
        "viewpoint": viewpoint,
        "viewpoint_place": viewpoint_place,
        "outlier": outlier,
    }


# ── the sync invariant (openspec add-geoplaces-near) ────────────────


class TestClusterCountSync:
    pytestmark = pytest.mark.usefixtures("amenity_poi_field")

    """Every cluster feature's count == near(anchor, z).count.

    Probes each tier band shape: tier A (cluster_max_zoom 7), B (9)
    and C (11) — full-clustering zooms and the hybrid transition band
    (where the importance split decides membership).
    """

    BANDS = ((7, (5, 6, 7, 8)), (9, (9, 10)), (11, (11, 12)))

    def test_cluster_counts_match_near_counts(self, client: Client) -> None:
        checked = 0
        for cmz, zooms in self.BANDS:
            for z in zooms:
                features = _tile_features(
                    z,
                    {
                        "lang": "de",
                        "category_tree": "amenity",
                        "cluster_max_zoom": cmz,
                        "cache_ttl_days": 0,
                    },
                )
                # cluster features carry no slug (twin individuals do);
                # singleton cells (count == 1) count as clusters too
                clusters = [f for f in features if not f["props"].get("slug")]
                assert clusters, (cmz, z)
                for feature in clusters:
                    lon, lat = _to_lnglat(feature)
                    response = client.get(
                        NEAR_URL,
                        {
                            "lat": f"{lat:.6f}",
                            "lon": f"{lon:.6f}",
                            "z": z,
                            "cluster_max_zoom": cmz,
                            "category_tree": "amenity",
                            "category_identifier": feature["props"][
                                "category_identifier"
                            ],
                            "limit": 25,
                        },
                    )
                    assert response.status_code == 200, response.content
                    body = response.json()
                    assert body["count"] == feature["props"]["count"], (
                        cmz,
                        z,
                        feature["props"],
                    )
                    assert len(body["data"]) == min(body["count"], 25)
                    checked += 1
        # sanity: the sweep exercised clusters of several sizes/zooms
        assert checked >= 12


# ── endpoint contract ───────────────────────────────────────────────


class TestClusterMode:
    pytestmark = pytest.mark.usefixtures("amenity_poi_field")

    def test_members_ordered_by_importance(
        self, client: Client, amenity_poi_field: dict[str, Any]
    ) -> None:
        response = client.get(
            NEAR_URL,
            {
                "lat": f"{LAT:.6f}",
                "lon": f"{LON:.6f}",
                "z": 5,
                "cluster_max_zoom": 7,
                "category_tree": "amenity",
                "limit": 25,
            },
        )
        assert response.status_code == 200, response.content
        body = response.json()
        importances = [entry["importance"] for entry in body["data"]]
        assert importances == sorted(importances, reverse=True)
        # the far-away outlier never leaks into the cell's members
        slugs = {entry["slug"] for entry in body["data"]}
        assert amenity_poi_field["outlier"].slug not in slugs

    def test_category_identifier_pins_one_cluster(self, client: Client) -> None:
        """One cell holds hut AND hotel clusters — the identifier pin
        separates them (this is the exact per-cluster count surface)."""
        kwargs: dict[str, Any] = {
            "lat": f"{LAT:.6f}",
            "lon": f"{LON:.6f}",
            "z": 5,
            "cluster_max_zoom": 7,
            "category_tree": "amenity",
        }
        huts = client.get(
            NEAR_URL, {**kwargs, "category_identifier": "accommodation.hut"}
        ).json()
        hotels = client.get(
            NEAR_URL, {**kwargs, "category_identifier": "accommodation.hotel"}
        ).json()
        assert huts["count"] == 30
        assert hotels["count"] == 2
        assert all(
            entry["category_identifier"] == "accommodation.hut"
            for entry in huts["data"]
        )


class TestProximityMode:
    pytestmark = pytest.mark.usefixtures("amenity_poi_field")

    def test_proximity_never_applies_cluster_split(
        self, client: Client, amenity_poi_field: dict[str, Any]
    ) -> None:
        """The what's-here click must see EVERY public place in radius:
        no importance split, no grid class — the viewpoint (importance
        50, graduated raw in every transition band) is returned right
        next to the low-importance huts."""
        response = client.get(
            NEAR_URL,
            {
                "lat": f"{LAT:.6f}",
                "lon": f"{LON:.6f}",
                "radius": 200,
                "fields": "slug,importance",
            },
        )
        assert response.status_code == 200, response.content
        slugs = {entry["slug"] for entry in response.json()["data"]}
        assert amenity_poi_field["viewpoint_place"].slug in slugs
        assert len(slugs) >= 3  # the viewpoint plus surrounding huts

    def test_nearest_places_within_radius(self, client: Client) -> None:
        response = client.get(
            NEAR_URL,
            {
                "lat": f"{LAT:.6f}",
                "lon": f"{LON:.6f}",
                "radius": 200,
                "fields": "slug,distance",
            },
        )
        assert response.status_code == 200, response.content
        body = response.json()
        assert body["count"] >= 3
        distances = [entry["distance"] for entry in body["data"]]
        assert distances == sorted(distances)
        # fields gating: only the requested keys ride the rows
        assert all(set(entry) == {"slug", "distance"} for entry in body["data"])

    def test_radius_capped_at_50km(self, client: Client) -> None:
        far = client.get(
            NEAR_URL,
            {"lat": f"{LAT:.6f}", "lon": f"{LON:.6f}", "radius": 5000000},
        )
        assert far.status_code == 200
        at_cap = client.get(
            NEAR_URL,
            {"lat": f"{LAT:.6f}", "lon": f"{LON:.6f}", "radius": 50000},
        )
        # the 0.5-degree outlier (~55 km) falls outside the 50 km cap
        assert far.json()["count"] == at_cap.json()["count"]

    def test_z_wins_over_radius(self, client: Client) -> None:
        both = client.get(
            NEAR_URL,
            {
                "lat": f"{LAT:.6f}",
                "lon": f"{LON:.6f}",
                "z": 5,
                "cluster_max_zoom": 7,
                "category_tree": "amenity",
                "category_identifier": "accommodation.hotel",
                "radius": 1,
            },
        )
        assert both.status_code == 200, both.content
        # cluster mode ignored the 1 m radius — the cell's hotels are in
        assert both.json()["count"] == 2


class TestOrdering:
    pytestmark = pytest.mark.usefixtures("amenity_poi_field")

    def test_cluster_mode_default_is_importance_desc(self, client: Client) -> None:
        response = client.get(
            NEAR_URL,
            {
                "lat": f"{LAT:.6f}",
                "lon": f"{LON:.6f}",
                "z": 5,
                "cluster_max_zoom": 7,
                "category_tree": "amenity",
                "category_identifier": "accommodation.hut",
                "limit": 25,
                "fields": "importance",
            },
        )
        importances = [e["importance"] for e in response.json()["data"]]
        assert importances == sorted(importances, reverse=True)

    def test_order_name_asc(self, client: Client) -> None:
        response = client.get(
            NEAR_URL,
            {
                "lat": f"{LAT:.6f}",
                "lon": f"{LON:.6f}",
                "z": 5,
                "cluster_max_zoom": 7,
                "category_tree": "amenity",
                "category_identifier": "accommodation.hut",
                "order": "name",
                "limit": 25,
                "fields": "name",
            },
        )
        names = [e["name"] for e in response.json()["data"]]
        assert names == sorted(names)

    def test_proximity_order_importance(self, client: Client) -> None:
        response = client.get(
            NEAR_URL,
            {
                "lat": f"{LAT:.6f}",
                "lon": f"{LON:.6f}",
                "radius": 200,
                "order": "importance",
                "fields": "importance",
            },
        )
        importances = [e["importance"] for e in response.json()["data"]]
        assert importances == sorted(importances, reverse=True)


class TestFieldsContract:
    pytestmark = pytest.mark.usefixtures("amenity_poi_field")

    def test_default_fields_are_the_popup_set(self, client: Client) -> None:
        response = client.get(
            NEAR_URL,
            {
                "lat": f"{LAT:.6f}",
                "lon": f"{LON:.6f}",
                "z": 5,
                "cluster_max_zoom": 7,
                "category_tree": "amenity",
                "limit": 1,
            },
        )
        entry = response.json()["data"][0]
        assert set(entry) == {
            "slug",
            "name",
            "importance",
            "category_identifier",
            "color",
            "parent_color",
            "elevation",
        }

    def test_offset_pager_and_count(self, client: Client) -> None:
        base = {
            "lat": f"{LAT:.6f}",
            "lon": f"{LON:.6f}",
            "z": 5,
            "cluster_max_zoom": 7,
            "category_tree": "amenity",
            "category_identifier": "accommodation.hut",
        }
        first = client.get(NEAR_URL, {**base, "limit": 10, "offset": 0}).json()
        second = client.get(NEAR_URL, {**base, "limit": 10, "offset": 10}).json()
        assert first["count"] == 30
        assert second["count"] == 30
        first_slugs = {entry["slug"] for entry in first["data"]}
        second_slugs = {entry["slug"] for entry in second["data"]}
        assert len(first_slugs | second_slugs) == 20

    def test_limit_validation(self, client: Client) -> None:
        response = client.get(NEAR_URL, {"lat": "46", "lon": "7", "limit": 26})
        # dmr maps validation errors to the repo's 400 problem shape
        assert response.status_code == 400, response.content

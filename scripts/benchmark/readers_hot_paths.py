"""Benchmark gate: hand-tuned vs readers-generated hot paths.

OpenSpec ``adopt-django-readers-query-optimization`` §4.1. Compares, per
hot endpoint, the current hand-tuned query prepare against the
readers-generated variant a conversion would ship (``spec_from_schema``
derived relation loading + reader-pair overrides for computed fields).
Projection code is identical on both sides — a conversion only replaces
the prepare step — so both variants share the same projection callable
and the measurement isolates the query work (dmr/HTTP overhead is out
of scope by construction).

Both variants materialize fully; wall time p50/p95 and queries/call are
reported. Decision rule (§4.3): convert only if p50 within ±5% and p95
not worse — otherwise keep the hand-tuned annotations and document the
decision at the query site.

Usage (lane DB with template data):
    scripts/lane-run.sh .venv/bin/python scripts/benchmark/readers_hot_paths.py
    scripts/lane-run.sh .venv/bin/python scripts/benchmark/readers_hot_paths.py --runs 50 --q alp

Query-construction code is copied verbatim from the controllers
(referenced inline). It will drift; the harness is a measuring tool —
rerun against the commit under decision and record output in ``_work/``.
"""

from __future__ import annotations

import argparse
import os
import statistics
import time
from collections.abc import Callable
from typing import Any

os.environ.setdefault("DJANGO_ENV", "test")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.settings")

import django

django.setup()

from django_readers import specs as readers_specs

from django.contrib.postgres.aggregates import JSONBAgg
from django.db import connection
from django.db.models import Case, F, Value, When
from django.db.models.functions import JSONObject
from django.test import RequestFactory

from server.apps.api.readers import spec_from_schema
from server.apps.translations import activate

WARMUP = 5

# A reader pair half: (queryset) -> queryset.
Prepare = Callable[[Any], Any]


def _pair(prepare: Prepare) -> tuple[Prepare, None]:
    return prepare, None


def _noop_pair() -> tuple[Prepare, None]:
    def prepare(queryset):
        return queryset

    return prepare, None


def _join_pair(*relations: str) -> tuple[Prepare, None]:
    def prepare(queryset):
        return queryset.select_related(*relations)

    return prepare, None


# ---------------------------------------------------------------------------
# Case: search_huts  (server/apps/huts/api/_hut.py HutSearchController.get)
# ---------------------------------------------------------------------------


def _hut_search_base_queryset(query):
    from server.apps.huts.models import Hut

    return Hut.objects.search(
        query=query.q,
        language=query.lang,
        threshold=query.threshold,
        is_active=True,
        is_public=True,
    )


def _hut_search_hand_prepare(query):
    def prepare(queryset):
        queryset = queryset.select_related(
            "hut_type_open",
            "hut_type_closed",
            "hut_type_open__symbol_detailed",
            "hut_type_open__symbol_simple",
            "hut_type_open__symbol_mono",
            "hut_type_closed__symbol_detailed",
            "hut_type_closed__symbol_simple",
            "hut_type_closed__symbol_mono",
        ).annotate(
            sources_data=JSONBAgg(
                JSONObject(
                    slug="org_set__slug",
                    name="org_set__name_i18n",
                    fullname="org_set__fullname_i18n",
                    link="orgs_source__link",
                    logo="org_set__logo",
                    public="org_set__is_public",
                    source_id="orgs_source__source_id",
                ),
                distinct=True,
            ),
        )
        if query.limit is not None:
            queryset = queryset[query.offset : query.offset + query.limit]
        return queryset

    return prepare


def _hut_search_readers_spec():
    """What a conversion would ship: derived spec + reader-pair overrides.

    ``HutSearchResultSchema`` declares no model-attr aliases for
    ``hut_type`` (the projection loop assembles that block from joined
    instances) and ``sources`` is a JSONBAgg aggregate — both are
    explicit overrides per the "computed fields as reader pairs"
    requirement; the derivation contributes the relation set.
    """
    from server.apps.huts.models import Hut
    from server.apps.huts.schemas._hut import HutSearchResultSchema

    def sources_pair():
        def prepare(queryset):
            return queryset.annotate(
                sources_data=JSONBAgg(
                    JSONObject(
                        slug="org_set__slug",
                        name="org_set__name_i18n",
                        fullname="org_set__fullname_i18n",
                        link="orgs_source__link",
                        logo="org_set__logo",
                        public="org_set__is_public",
                        source_id="orgs_source__source_id",
                    ),
                    distinct=True,
                ),
            )

        return prepare, None

    return spec_from_schema(
        Hut,
        HutSearchResultSchema,
        relations_only=True,
        overrides={
            # capacity is assembled by the projection loop from plain
            # columns — no model field exists, so give the derivation a
            # no-op override instead of letting it reject the schema.
            "capacity": _noop_pair(),
            "hut_type": _join_pair(
                "hut_type_open",
                "hut_type_closed",
                "hut_type_open__symbol_detailed",
                "hut_type_open__symbol_simple",
                "hut_type_open__symbol_mono",
                "hut_type_closed__symbol_detailed",
                "hut_type_closed__symbol_simple",
                "hut_type_closed__symbol_mono",
            ),
            "sources": sources_pair(),
        },
    )


def _project_hut_search(huts, query, media_url, request):
    """Projection loop — copied verbatim from HutSearchController.get."""
    from server.apps.api.projection import project_fields
    from server.apps.huts.api._hut import _hut_type_symbol_block
    from server.apps.huts.schemas._hut import HutSearchResultSchema

    results = []
    for hut in huts:
        result = {
            "name": hut.name_i18n,
            "slug": hut.slug,
            "capacity": {
                "open": hut.capacity_open,
                "closed": hut.capacity_closed,
            },
            "location": hut.location,
            "elevation": hut.elevation,
            "score": hut.combined_score,
        }
        result["hut_type"] = {
            "open": {
                "slug": hut.hut_type_open.slug,
                "name": hut.hut_type_open.name_i18n,
                "color": hut.hut_type_open.color,
                "symbol": _hut_type_symbol_block(request, hut.hut_type_open),
            }
            if hut.hut_type_open
            else None,
            "closed": {
                "slug": hut.hut_type_closed.slug,
                "name": hut.hut_type_closed.name_i18n,
                "color": hut.hut_type_closed.color,
                "symbol": _hut_type_symbol_block(request, hut.hut_type_closed),
            }
            if hut.hut_type_closed
            else None,
        }
        result["sources"] = [
            {
                **src,
                "logo": f"{media_url}{src['logo']}" if src.get("logo") else None,
            }
            for src in (hut.sources_data or [])
            if src.get("slug") is not None
        ]
        if hut.photos:
            result["avatar"] = f"{media_url}{hut.photos}"
        else:
            result["avatar"] = None

        safe = HutSearchResultSchema(**result).model_dump(exclude_unset=True)
        results.append(
            project_fields(
                safe,
                query,
                "huts",
                {"hut_types": "hut_type", "sources": "sources"},
            )
        )
    return results


# ---------------------------------------------------------------------------
# Case: huts.geojson  (HutsGeojsonController.get, embed_all variant)
# ---------------------------------------------------------------------------


def _huts_geojson_prepare(media_url: str):
    """The hand-tuned SQL aggregate (identical on both sides).

    The whole FeatureCollection is assembled in PostgreSQL (``GeoJSON``
    expression over ``JSONObject``/``JSONBAgg`` annotations); a
    readers-generated variant would load every matching hut into Python
    and project per row — strictly more work, and the design explicitly
    keeps JSONBAgg where it wins. Benchmarked hand-only: the readers
    column is the decision, not a candidate.
    """
    from server.apps.huts.api._hut import get_json_obj

    def prepare(queryset):
        queryset = queryset.select_related(
            "availability_source_ref", "hut_type_open", "hut_type_closed", "hut_owner"
        ).annotate(
            has_availability=Case(
                When(availability_source_ref__isnull=False, then=Value(True)),
                default=Value(False),
            ),
            availability_source_ref__slug=F("availability_source_ref__slug"),
            **get_json_obj(
                flat=False,
                values={
                    "type": {
                        "open": {
                            "slug": "hut_type_open__slug",
                            "order": "hut_type_open__order",
                        },
                        "closed": {
                            "slug": "hut_type_closed__slug",
                            "order": "hut_type_closed__order",
                        },
                    },
                },
            ),
            **get_json_obj(
                flat=False,
                values={
                    "owner": {
                        "name": "hut_owner__name_i18n",
                        "slug": "hut_owner__slug",
                    }
                },
            ),
            **get_json_obj(
                flat=False,
                values={
                    "capacity": {
                        "if_open": "capacity_open",
                        "if_closed": "capacity_closed",
                    }
                },
            ),
            sources=JSONBAgg(
                JSONObject(
                    slug="org_set__slug",
                    link="orgs_source__link",
                    source_id="orgs_source__source_id",
                ),
                distinct=True,
            ),
        )
        return queryset

    return prepare


def _project_huts_geojson(prepared_queryset):
    from server.apps.huts.api.expressions import GeoJSON

    properties = [
        "id",
        "slug",
        "elevation",
        "name",
        "has_availability",
        "type",
        "owner",
        "capacity",
        "sources",
    ]
    return prepared_queryset.aggregate(
        GeoJSON(geom_field="location", fields=properties, decimals=5),
    )["geojson"]


# ---------------------------------------------------------------------------
# Cases: geo search / nearby  (server/apps/geometries/api.py)
# ---------------------------------------------------------------------------


def _geoplace_search_base(query):
    """Base filters — the part of search_geoplaces before the prepare."""
    from server.apps.geometries.models import GeoPlace
    from server.apps.geometries.presenters import apply_type_filters

    queryset = GeoPlace.objects.filter(is_active=True, is_public=True).only(
        "id",
        "name",
        "i18n",
        "location",
        "elevation",
        "importance",
        "country_code",
    )
    if query.min_importance > 0:
        queryset = queryset.filter(importance__gte=query.min_importance)
    if query.countries:
        queryset = queryset.filter(
            country_code__in=[c.upper() for c in query.countries]
        )
    return apply_type_filters(queryset, query.types, query.categories)


def _geoplace_fuzzy(queryset, query):
    """Fuzzy annotations, dedupe window, ordering, slice — copied from
    search_geoplaces (applied AFTER the prepare, as in the controller)."""
    from django.conf import settings
    from django.contrib.gis.db.models import PointField
    from django.contrib.postgres.search import TrigramSimilarity
    from django.db.models import (
        Case,
        CharField,
        ExpressionWrapper,
        F,
        FloatField,
        Func,
        Value,
        When,
        Window,
    )
    from django.db.models.fields.json import KeyTextTransform
    from django.db.models.functions import (
        Cast,
        Coalesce,
        Greatest,
        Lower,
        RowNumber,
    )

    q = query.q.strip()
    default_language = settings.LANGUAGE_CODE
    requested_language = query.lang
    translated_name = None
    if requested_language != default_language:
        translated_name = Cast(
            KeyTextTransform(f"name_{requested_language}", "i18n"),
            output_field=CharField(),
        )
        primary_similarity = TrigramSimilarity(translated_name, q)
    else:
        primary_similarity = TrigramSimilarity("name", q)

    translation_similarity = Value(0.0)
    if requested_language != default_language and translated_name is not None:
        translation_similarity = ExpressionWrapper(
            Value(0.3) * TrigramSimilarity("name", q),
            output_field=FloatField(),
        )

    similarity_expr = ExpressionWrapper(
        Greatest(primary_similarity, translation_similarity),
        output_field=FloatField(),
    )

    tokens = [token for token in q.split() if token]
    if len(tokens) > 1:
        token_match_score = sum(
            1.0 for token in tokens[:3] if token.lower() in q.lower()
        ) / min(len(tokens), 3)
        token_match = Value(token_match_score, output_field=FloatField())
    else:
        token_match = Value(0.0)

    if translated_name is not None:
        prefix_match = Case(
            When(name__istartswith=q, then=Value(1.0)),
            When(
                **{f"i18n__name_{requested_language}__istartswith": q},
                then=Value(1.0),
            ),
            default=Value(0.0),
            output_field=FloatField(),
        )
    else:
        prefix_match = Case(
            When(name__istartswith=q, then=Value(1.0)),
            default=Value(0.0),
            output_field=FloatField(),
        )

    normalized_importance = Case(
        When(importance__lt=0, then=Value(0.0)),
        When(importance__gt=100, then=Value(1.0)),
        default=Coalesce(F("importance"), Value(0)) / Value(100.0),
        output_field=FloatField(),
    )
    rank_score = ExpressionWrapper(
        Value(0.8) * similarity_expr + Value(0.2) * normalized_importance,
        output_field=FloatField(),
    )

    queryset = queryset.annotate(
        similarity=similarity_expr,
        rank_score=rank_score,
        prefix_match=prefix_match,
        fts_rank=Value(0.0),
        token_match=token_match,
    ).filter(similarity__gte=query.threshold)

    if query.deduplicate:
        grid_size = Value(0.00005)
        snapped_location = Func(
            F("location"),
            grid_size,
            grid_size,
            function="ST_SnapToGrid",
            output_field=PointField(),
        )
        normalized_name = Lower(F("name"))
        duplicate_rank = Window(
            expression=RowNumber(),
            partition_by=[
                snapped_location,
                normalized_name,
                F("country_code"),
            ],
            order_by=[
                F("prefix_match").desc(nulls_last=True),
                F("token_match").desc(nulls_last=True),
                F("rank_score").desc(nulls_last=True),
                F("fts_rank").desc(nulls_last=True),
                F("similarity").desc(nulls_last=True),
                F("id").asc(),
            ],
        )
        queryset = queryset.annotate(duplicate_rank=duplicate_rank).filter(
            duplicate_rank=1
        )

    return queryset.order_by(
        "-prefix_match",
        "-token_match",
        "-rank_score",
        "-fts_rank",
        "-similarity",
    )[query.offset : query.offset + query.limit]


def _geoplace_hand_prepare():
    from server.apps.geometries.presenters import annotate_sources, prefetch_categories

    def prepare(queryset):
        return annotate_sources(prefetch_categories(queryset))

    return prepare


def _geoplace_readers_spec(nearby: bool):
    """Derived prepare for search_geoplaces / nearby_geoplaces.

    The projection loop resolves symbol URLs per category with the
    request context — fields the wire schema does not declare
    (``CategoryPlaceTypeSchema.symbol`` is a resolved dict, not a model
    field) — and the derivation API cannot inject overrides into the
    nested category subtree. ``categories`` therefore ships as an
    explicit reader pair reproducing ``prefetch_categories()``; the
    derivation contributes the remaining relation set and ``sources``
    / ``distance`` ship as pairs per "computed fields as reader pairs".
    """
    from server.apps.geometries.models import GeoPlace
    from server.apps.geometries.presenters import (
        annotate_sources,
        prefetch_categories,
    )
    from server.apps.geometries.schemas._output import (
        GeoPlaceNearbySchema,
        GeoPlaceSearchSchema,
    )

    schema = GeoPlaceNearbySchema if nearby else GeoPlaceSearchSchema
    overrides: dict[str, Any] = {
        "categories": _pair(prefetch_categories),
        "sources": _pair(annotate_sources),
    }
    if nearby:

        def distance_pair():
            from django.contrib.gis.db.models.functions import Distance
            from django.contrib.gis.geos import Point

            point = Point(7.6488, 46.0342, srid=4326)

            def prepare(queryset):
                return queryset.annotate(distance=Distance("location", point))

            return prepare, None

        overrides["distance"] = distance_pair()

    return spec_from_schema(
        GeoPlace,
        schema,
        relations_only=True,
        overrides=overrides,
    )


def _project_geoplaces(places, media_url, request, *, nearby: bool = False):
    """Projection loop — copied from search/nearby controllers."""
    from server.apps.geometries.presenters import build_categories_data, build_sources

    results = []
    for place in places:
        result = {
            "name": place.name_i18n,
            "country_code": str(place.country_code) if place.country_code else None,
            "id": place.id,
            "elevation": place.elevation,
            "importance": place.importance,
            "location": {
                "lat": place.location.y if place.location else None,
                "lon": place.location.x if place.location else None,
            },
        }
        if nearby:
            distance_m = (
                place.distance.m if hasattr(place.distance, "m") else place.distance
            )
            result["distance"] = round(distance_m, 2) if distance_m else None
        else:
            result["score"] = place.rank_score
        result["categories"] = build_categories_data(place, request) or []
        build_sources(result, place, media_url)
        results.append(result)
    return results


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


def _bench(fn: Callable[[], Any], runs: int) -> dict:
    for _ in range(WARMUP):
        fn()
    return _timed(fn, runs)


def _timed(fn: Callable[[], Any], runs: int) -> dict:
    times: list[float] = []
    for _ in range(runs):
        t0 = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t0) * 1000)
    return {
        "p50": statistics.median(times),
        "p95": sorted(times)[int(len(times) * 0.95) - 1],
        "mean": statistics.fmean(times),
        "queries": _queries_per_call(fn, runs),
    }


def _queries_per_call(fn: Callable[[], Any], runs: int) -> float:
    start = len(connection.queries_log)
    connection.force_debug_cursor = True
    try:
        for _ in range(runs):
            fn()
        return (len(connection.queries_log) - start) / runs
    finally:
        connection.force_debug_cursor = False
        connection.queries_log.clear()


def _bench_pair(hand: Callable[[], Any], readers: Callable[[], Any], runs: int) -> dict:
    """Interleaved paired measurement.

    The dev/lane postgres is shared, so sequential rounds see different
    interference per variant; alternating hand/readers per run makes
    that noise common-mode. Query counts are taken in a separate
    sequential pass (debug-cursor capture cannot interleave).
    """
    for _ in range(WARMUP):
        hand()
    for _ in range(WARMUP):
        readers()
    hand_times: list[float] = []
    readers_times: list[float] = []
    for _ in range(runs):
        t0 = time.perf_counter()
        hand()
        hand_times.append((time.perf_counter() - t0) * 1000)
        t0 = time.perf_counter()
        readers()
        readers_times.append((time.perf_counter() - t0) * 1000)

    def _stats(times):
        return {
            "p50": statistics.median(times),
            "p95": sorted(times)[int(len(times) * 0.95) - 1],
            "mean": statistics.fmean(times),
        }

    return {
        "hand": {**_stats(hand_times), "queries": _queries_per_call(hand, runs)},
        "readers": {
            **_stats(readers_times),
            "queries": _queries_per_call(readers, runs),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark hand-tuned vs readers-generated hot paths (OpenSpec §4)."
    )
    parser.add_argument("--runs", type=int, default=50)
    parser.add_argument(
        "--q",
        type=str,
        default="",
        help="Search term; defaults to a probe of the first hut name.",
    )
    options = vars(parser.parse_args())
    from server.apps.geometries.api import GeoNearbyQuery, GeoSearchQuery
    from server.apps.geometries.models import GeoPlace
    from server.apps.huts.api._hut import HutSearchQuery

    runs = options["runs"]
    probe = options["q"] or _probe_term()
    activate("de")
    # The 15s default guard trips on the trigram/window searches when
    # the shared dev postgres is busy; a bench session may use a
    # bigger budget (connection-scoped, dies with the process).
    with connection.cursor() as cursor:
        cursor.execute("SET statement_timeout = '60s'")
    request = RequestFactory(SERVER_NAME="localhost").get("/benchmark")
    media_url = request.build_absolute_uri("/media/")

    hut_query = HutSearchQuery(q=probe)
    place_query = GeoSearchQuery(q=probe)
    nearby_query = GeoNearbyQuery(lat=46.0342, lon=7.6488)

    # search_huts: hand vs readers prepare, shared projection.
    hut_readers_prepare, _ = readers_specs.process(_hut_search_readers_spec())

    def hut_hand():
        qs = _hut_search_hand_prepare(hut_query)(_hut_search_base_queryset(hut_query))
        return _project_hut_search(qs, hut_query, media_url, request)

    def hut_readers():
        qs = hut_readers_prepare(_hut_search_base_queryset(hut_query))
        return _project_hut_search(qs, hut_query, media_url, request)

    # huts.geojson: hand only (SQL aggregate — readers is the decision).
    from server.apps.huts.models import Hut

    def geojson_hand():
        qs = _huts_geojson_prepare(media_url)(
            Hut.objects.filter(is_active=True, is_public=True)
        )
        return _project_huts_geojson(qs)

    # geo search / nearby: hand vs readers prepare, shared projection.
    # Controller order: the prepare slots in BEFORE the fuzzy
    # annotations (base filters -> prefetch/annotate -> fuzzy).
    place_hand = _geoplace_hand_prepare()
    place_readers, _ = readers_specs.process(_geoplace_readers_spec(nearby=False))
    nearby_readers, _ = readers_specs.process(_geoplace_readers_spec(nearby=True))

    def place_hand_fn():
        qs = _geoplace_fuzzy(
            place_hand(_geoplace_search_base(place_query)), place_query
        )
        return _project_geoplaces(qs, media_url, request)

    def place_readers_fn():
        qs = _geoplace_fuzzy(
            place_readers(_geoplace_search_base(place_query)), place_query
        )
        return _project_geoplaces(qs, media_url, request)

    # nearby: distance filter + annotation per the nearby controller.
    def _nearby_base():
        from django.contrib.gis.geos import Point
        from django.contrib.gis.measure import D

        point = Point(nearby_query.lon, nearby_query.lat, srid=4326)
        return (
            point,
            GeoPlace.objects.filter(
                is_active=True,
                is_public=True,
                location__distance_lte=(point, D(m=nearby_query.radius)),
            ).only(
                "id",
                "name",
                "i18n",
                "location",
                "elevation",
                "importance",
                "country_code",
            ),
        )

    def nearby_hand_fn():
        from django.contrib.gis.db.models.functions import Distance

        point, queryset = _nearby_base()
        qs = place_hand(queryset)
        qs = qs.annotate(distance=Distance("location", point)).order_by("distance")
        qs = qs[nearby_query.offset : nearby_query.offset + nearby_query.limit]
        return _project_geoplaces(qs, media_url, request, nearby=True)

    def nearby_readers_fn():
        from django.contrib.gis.db.models.functions import Distance

        point, queryset = _nearby_base()
        qs = nearby_readers(queryset)
        qs = qs.annotate(distance=Distance("location", point)).order_by("distance")
        qs = qs[nearby_query.offset : nearby_query.offset + nearby_query.limit]
        return _project_geoplaces(qs, media_url, request, nearby=True)

    cases = [
        ("search_huts", hut_hand, hut_readers),
        ("huts.geojson", geojson_hand, None),
        ("search_geoplaces", place_hand_fn, place_readers_fn),
        ("nearby_geoplaces", nearby_hand_fn, nearby_readers_fn),
    ]

    print(
        f"benchmark_readers: N={runs} warmup={WARMUP} q={probe!r} "
        f"lang=de (times in ms, queries per call)"
    )
    header = (
        f"{'case':<20} {'variant':<10} {'p50':>8} {'p95':>8} {'mean':>8} {'queries':>8}"
    )
    print(header)
    print("-" * len(header))
    results = {}
    for name, hand, readers in cases:
        if readers is None:
            results[name] = {"hand": _bench(hand, runs)}
        else:
            results[name] = _bench_pair(hand, readers, runs)
        print(
            f"{name:<20} {'hand':<10} "
            f"{results[name]['hand']['p50']:>8.2f} "
            f"{results[name]['hand']['p95']:>8.2f} "
            f"{results[name]['hand']['mean']:>8.2f} "
            f"{results[name]['hand']['queries']:>8.1f}"
        )
        if readers is not None:
            print(
                f"{'':<20} {'readers':<10} "
                f"{results[name]['readers']['p50']:>8.2f} "
                f"{results[name]['readers']['p95']:>8.2f} "
                f"{results[name]['readers']['mean']:>8.2f} "
                f"{results[name]['readers']['queries']:>8.1f}"
            )

    print()
    print("§4.3 decision rule: convert if p50 within ±5% and p95 not worse")
    for name, data in results.items():
        if "readers" not in data:
            print(f"  {name:<20} KEEP (SQL aggregate; no readers candidate exists)")
            continue
        hand, rd = data["hand"], data["readers"]
        p50_delta = (rd["p50"] - hand["p50"]) / hand["p50"] * 100
        p95_ok = rd["p95"] <= hand["p95"]
        # Literal §4.3 rule: convert at parity (p50 within the ±5%
        # band) with p95 not worse. Deltas beyond the band are noise
        # on identical SQL — reported, not treated as a conversion
        # argument.
        within = abs(p50_delta) <= 5 and p95_ok
        direction = "faster" if p50_delta < 0 else "slower"
        verdict = "CONVERT eligible" if within else "KEEP"
        print(
            f"  {name:<20} {verdict} "
            f"(p50 {p50_delta:+.1f}% {direction}, p95 {'ok' if p95_ok else 'worse'})"
        )


def _probe_term() -> str:
    from server.apps.huts.models import Hut

    hut = (
        Hut.objects.filter(is_active=True, is_public=True)
        .only("name")
        .order_by("pk")
        .first()
    )
    if hut is None:
        print("WARNING: no huts in database — run on a seeded lane DB")
        raise SystemExit(2)
    return hut.name.split()[0] if hut.name else "hut"


if __name__ == "__main__":
    main()

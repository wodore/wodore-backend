"""Benchmark get_hut: wall time + SQL cost, warm cache.

Usage (lane): ./scripts/lane-run.sh .venv/bin/python scripts/benchmark/get_hut.py
Writes a compact table to stdout; run on main for the baseline, on the
branch for the comparison.
"""

import os
import statistics
import time

os.environ.setdefault("DJANGO_ENV", "test")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.settings")

import django

django.setup()

from django.conf import settings

settings.ALLOWED_HOSTS = [*settings.ALLOWED_HOSTS, "testserver"]

from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext

from server.apps.huts.models import Hut

WARMUP = 5
RUNS = 50


def bench(client: Client, url: str) -> dict:
    for _ in range(WARMUP):
        assert client.get(url).status_code == 200, url

    times: list[float] = []
    with CaptureQueriesContext(connection) as ctx:
        for _ in range(RUNS):
            t0 = time.perf_counter()
            resp = client.get(url)
            times.append((time.perf_counter() - t0) * 1000)
            assert resp.status_code == 200, (url, resp.status_code)

    sql_ms = sum(float(q["time"]) for q in ctx.captured_queries) / RUNS
    return {
        "p50": statistics.median(times),
        "p95": sorted(times)[int(len(times) * 0.95) - 1],
        "mean": statistics.fmean(times),
        "queries": len(ctx.captured_queries) / RUNS,
        "sql_ms": sql_ms,
    }


def main() -> None:
    slugs = list(
        Hut.objects.filter(is_active=True, is_public=True, image_set__isnull=False)
        .distinct()
        .values_list("slug", flat=True)[:3]
    )
    if not slugs:
        slugs = list(
            Hut.objects.filter(is_active=True, is_public=True).values_list(
                "slug", flat=True
            )[:3]
        )
    print(f"slugs: {', '.join(slugs)}  (warmup={WARMUP}, runs={RUNS})")

    client = Client()
    variants = {
        "full detail": [f"/v1/huts/{slug}?lang=de" for slug in slugs],
        "narrowed": [
            f"/v1/huts/{slug}?lang=de&fields[huts]=slug,name,elevation,images,sources"
            for slug in slugs
        ],
    }
    for label, urls in variants.items():
        results = [bench(client, url) for url in urls]
        agg = {k: statistics.fmean(r[k] for r in results) for k in results[0]}
        print(
            f"{label:12s} p50={agg['p50']:7.1f}ms p95={agg['p95']:7.1f}ms "
            f"mean={agg['mean']:7.1f}ms queries/req={agg['queries']:.1f} "
            f"sql={agg['sql_ms']:6.1f}ms"
        )


if __name__ == "__main__":
    main()

"""0054 slug re-mint migration: memory-bounded grammar repair.

Staging reality behind this fix: 187 156 of 369 387 geoplaces (50.6%)
violate the slug grammar, and the original implementation materialized
every violating row as a full model instance plus one uniqueness probe
per re-mint — OOM-killed inside the migrate job's 512 Mi limit. The
re-mint now streams id/slug chunks through a server-side cursor,
tracks the collision domain in one Python set and writes ``bulk_update``
batches; these tests pin that contract (grammar, uniqueness, shape,
no-op path, idempotency, collision retry, multi-batch behavior).

Violating slugs must be seeded with the live check constraint dropped
(``save()`` bypasses ``clean()``, but the constraint rejects the DML
itself) — same bracket pattern as the images 0033/0034 migration tests.
"""

from __future__ import annotations

import importlib
import re
from typing import Any

import pytest
from pytest_django.plugin import DjangoDbBlocker

from django.contrib.gis.geos import Point

from server.apps.geometries.converters import SLUG_GRAMMAR_RE
from server.apps.geometries.models import GeoPlace

pytestmark = [pytest.mark.django_db]

MIGRATION = "server.apps.geometries.migrations.0054_alter_geoplace_slug_and_more"
CONSTRAINT_NAME = "geometries_geoplace_slug_grammar_valid"


class _RealApps:
    """Migrations get a historical registry; the re-mint only calls
    ``get_model()``, so the live registry exercises the same code path."""

    def get_model(self, app_label: str, model_name: str) -> Any:
        from django.apps import apps

        return apps.get_model(app_label, model_name)


def _constraint() -> Any:
    return next(
        constraint
        for constraint in GeoPlace._meta.constraints
        if constraint.name == CONSTRAINT_NAME
    )


@pytest.fixture(scope="module", autouse=True)
def legacy_schema(django_db_setup: None, django_db_blocker: DjangoDbBlocker):
    """Pre-0054 grammar for the whole module: no check constraint, so
    grammar-violating slugs can be seeded. Re-added on teardown — if a
    test leaves violating rows behind, that re-add fails loudly."""
    from django.db import connection

    with django_db_blocker.unblock():
        with connection.schema_editor() as editor:
            editor.remove_constraint(GeoPlace, _constraint())
    yield
    with django_db_blocker.unblock():
        with connection.schema_editor() as editor:
            editor.add_constraint(GeoPlace, _constraint())


_seed_seq = iter(range(10_000_000))  # unique per-call seed placeholders


def make_place(slug: str) -> GeoPlace:
    """Create a place with an explicit slug; save() keeps a non-empty
    slug (it only mints when the slug is empty) — the empty-slug row is
    forced through queryset .update() instead."""
    place = GeoPlace(
        name="Test Berg",
        location=Point(7.65, 45.98, srid=4326),
        country_code="CH",
        is_active=True,
        is_public=True,
    )
    place.slug = slug or f"seed-{next(_seed_seq):07d}"
    place.save()
    if not slug:
        GeoPlace.objects.filter(pk=place.pk).update(slug="")
    return place


def run_re_mint() -> Any:
    migration = importlib.import_module(MIGRATION)
    return migration.re_mint_invalid_slugs(_RealApps(), None)


class TestReMintInvalidSlugs:
    def test_remints_violating_and_preserves_valid(
        self, capsys: pytest.CaptureFixture[str]
    ):
        """Synthetic mix: every violating shape known from the imports
        (no separator, uppercase, empty, non-slug charset, unicode) is
        re-minted to the minted shape; valid legacy shapes are kept."""
        violating = {
            "zermatt": "zermatt",  # separator-less (the staging case)
            "gornergrat1": "gornergra",  # separator-less; base truncated to 9
            "ZERMATT-HORN": "zermatt-h",  # uppercase → charset violation
            "bad.slug": "badslug",  # dot: outside the slug charset
            "zürich": "zrich",  # unicode → charset violation
            "ü": "place",  # no valid charset chars at all → fallback base
            "": "place",  # empty slug → fallback base
        }
        valid = ["vending_machine", "information-5h9", "dammastock-n1ce", "-"]
        valid_places = [make_place(slug) for slug in valid]
        violating_places = {make_place(slug): slug for slug in violating}

        run_re_mint()

        for place, old in violating_places.items():
            place.refresh_from_db()
            expected_base = violating[old]
            assert re.fullmatch(SLUG_GRAMMAR_RE, place.slug), place.slug
            assert re.fullmatch(rf"{expected_base}-[a-z0-9]{{5}}", place.slug), (
                old,
                place.slug,
            )
            assert len(place.slug) <= 15
        for place in valid_places:
            place.refresh_from_db()
            assert place.slug in valid  # untouched
        slugs = list(GeoPlace.objects.values_list("slug", flat=True))
        assert len(slugs) == len(set(slugs))  # unique across the table
        assert GeoPlace.objects.exclude(slug__regex=f"^{SLUG_GRAMMAR_RE}$").count() == 0
        assert "re-minted" in capsys.readouterr().out

    def test_all_valid_is_noop(self, capsys: pytest.CaptureFixture[str]):
        valid_places = [
            make_place(slug)
            for slug in ["vending_machine", "information-5h9", "matterhorn-7q2x"]
        ]
        before = {place.pk: place.slug for place in valid_places}

        run_re_mint()

        for place in valid_places:
            place.refresh_from_db()
            assert place.slug == before[place.pk]
        out = capsys.readouterr().out
        assert "no grammar-violating slugs" in out

    def test_idempotent_rerun(self, capsys: pytest.CaptureFixture[str]):
        make_place("zermatt")
        make_place("vending_machine")

        run_re_mint()
        after_first = dict(GeoPlace.objects.values_list("id", "slug"))

        run_re_mint()  # retried job: nothing left to fix, nothing changes
        assert dict(GeoPlace.objects.values_list("id", "slug")) == after_first
        assert "no grammar-violating slugs" in capsys.readouterr().out

    def test_collision_with_existing_slug_retries(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """The first mint candidate collides with an existing slug — the
        set check must force a re-draw instead of trusting randomness."""
        migration = importlib.import_module(MIGRATION)
        make_place("zermatt-aaaaa")  # occupies the first candidate
        place = make_place("zermatt")

        # secrets.choice → deterministic draw order: aaaaa (taken), bbbbb
        plan = iter("a" * 5 + "b" * 5)

        def fake_choice(alphabet: str) -> str:
            return next(plan)

        monkeypatch.setattr(migration.secrets, "choice", fake_choice)
        migration.re_mint_invalid_slugs(_RealApps(), None)

        place.refresh_from_db()
        assert place.slug == "zermatt-bbbbb"

    def test_uniqueness_across_batches(self, monkeypatch: pytest.MonkeyPatch):
        """Many violating rows sharing one base must stay unique when the
        re-mint spans several bulk_update batches (chunked path)."""
        migration = importlib.import_module(MIGRATION)
        monkeypatch.setattr(migration, "CHUNK_SIZE", 5)
        places = [make_place(f"zermattlong{n:03d}") for n in range(1, 13)]

        migration.re_mint_invalid_slugs(_RealApps(), None)

        slugs = [GeoPlace.objects.get(pk=place.pk).slug for place in places]
        assert len(slugs) == len(set(slugs))
        for slug in slugs:
            assert re.fullmatch(r"zermattlo-[a-z0-9]{5}", slug), slug

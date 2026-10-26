"""parties 0003 re-mint migration tests.

The re-mint streams ``.only()`` rows, mints the 0054 shape
(``{base<=9}-{5 alnum}``), keeps the collision domain in a set and is
re-runnable: rows already matching the minted shape within the 15-char
column are excluded, so a retried run finds nothing left to change.
The skip predicate is length-aware — the shape alone spans up to 18
chars, and legacy name-based slugs in the 16-18 char overlap must be
re-minted or the ALTER to varchar(15) fails (the staging 0003 bug).
``extra.osm_name`` values must never move — they are the import
identity.

The live test schema is post-0003 (slug varchar(15)); the module
fixture widens the column so legacy overlong slugs can be seeded —
the pre-migration reality the re-mint operates on (same bracket
pattern as the geometries 0054 migration tests).
"""

from __future__ import annotations

import importlib
import re
from collections.abc import Iterator
from typing import Any

import pytest
from pytest_django.plugin import DjangoDbBlocker

from tests.factories.parties import PartyFactory

from server.apps.parties.models import Party

pytestmark = pytest.mark.django_db

MIGRATION = "server.apps.parties.migrations.0003_party_extra_and_slug_remint"
MINTED = re.compile(r"^[a-z0-9]{1,9}-[a-z0-9]{5,8}$")


def _migration() -> Any:
    return importlib.import_module(MIGRATION)


class _RealApps:
    """Migrations get a historical registry; the re-mint only calls
    ``get_model()``, so the live registry exercises the same code path
    (same pattern as the 0054 re-mint tests)."""

    def get_model(self, app_label: str, model_name: str) -> Any:
        from django.apps import apps

        return apps.get_model(app_label, model_name)


def _run_remint() -> None:
    _migration().re_mint_slugs(_RealApps(), None)


@pytest.fixture(scope="module", autouse=True)
def legacy_slug_width(
    request: pytest.FixtureRequest, django_db_blocker: DjangoDbBlocker
) -> Iterator[None]:
    """Slug column at varchar(50) for the whole module — the pre-0003
    width, so legacy overlong slugs (up to 50 chars) can be seeded.
    Shrunk back on teardown — fails loudly if a test leaves overlong
    rows behind."""
    request.getfixturevalue("django_db_setup")  # the test DB must exist
    from django.db import connection

    with django_db_blocker.unblock():
        with connection.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE parties_party ALTER COLUMN slug TYPE varchar(50)"
            )
    yield
    with django_db_blocker.unblock():
        with connection.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE parties_party ALTER COLUMN slug TYPE varchar(15)"
            )


class TestReMintSlugs:
    def test_legacy_slugs_re_minted_to_shape(self):
        # Legacy-style slug (normalized name, underscore separator) that
        # still fits the post-migration varchar(15) column — the re-mint
        # logic is the unit under test, not Postgres length enforcement.
        # ``extra.osm_name`` mirrors the post-backfill state.
        party = PartyFactory(
            slug="legacy_volg1",
            name="Coop Supermarkt",
            extra={"osm_name": "coop_supermarkt"},
        )
        assert not MINTED.fullmatch(party.slug)  # the legacy value

        _run_remint()

        party.refresh_from_db()
        assert MINTED.fullmatch(party.slug)
        assert len(party.slug) <= 15
        assert party.slug.startswith("coopsupe-")
        assert party.extra["osm_name"] == "coop_supermarkt"  # never moves

    def test_all_slugs_unique_after_re_mint(self):
        for name in ("Volg", "Volg Zentrum", "Migros", "SAC Bern", "Denner"):
            PartyFactory(name=name)

        _run_remint()

        slugs = list(Party.objects.values_list("slug", flat=True))
        assert len(slugs) == len(set(slugs))
        assert all(MINTED.fullmatch(slug) for slug in slugs)

    def test_re_run_is_noop_for_minted_slugs(self):
        PartyFactory(slug="legacy_slug", name="Coop")
        _run_remint()
        party = Party.objects.get(name="Coop")
        slug = party.slug

        _run_remint()  # already minted -> excluded

        party.refresh_from_db()
        assert party.slug == slug

    def test_overlong_minted_looking_slug_re_minted(self):
        """Regression (staging 0003 failure): legacy name-based slugs can
        coincidentally match the minted shape while exceeding the 15-char
        column — froissard-bastien/giovanni-frapolli (17), skiclub-martigny
        (16). Those rows must be re-minted; a genuine minted slug that
        fits the column is untouched, and a re-run is a no-op."""
        overlong = ["froissard-bastien", "giovanni-frapolli", "skiclub-martigny"]
        for slug in overlong:  # the overlap the old predicate missed
            assert MINTED.fullmatch(slug) and len(slug) > 15
        kept = PartyFactory(slug="volg-5x2k9", name="Volg")
        assert MINTED.fullmatch(kept.slug) and len(kept.slug) <= 15
        overlong_parties = [
            PartyFactory(slug=slug, name=slug.replace("-", " ").title())
            for slug in overlong
        ]

        _run_remint()

        for party in overlong_parties:
            party.refresh_from_db()
            assert MINTED.fullmatch(party.slug), party.slug
            assert len(party.slug) <= 15
        kept.refresh_from_db()
        assert kept.slug == "volg-5x2k9"  # genuine minted, fits: kept

        # Retried job: everything now matches the shape within 15 chars
        # — a second run must find nothing left to change.
        after = dict(Party.objects.values_list("id", "slug"))
        _run_remint()
        assert dict(Party.objects.values_list("id", "slug")) == after

    def test_overlong_slugs_across_batches(self, monkeypatch: pytest.MonkeyPatch):
        """Overlong minted-looking slugs spanning several bulk_update
        batches are all re-minted and stay unique (chunked path)."""
        migration = _migration()
        monkeypatch.setattr(migration, "CHUNK_SIZE", 5)
        # 16 chars each (9-char base, 6-char suffix), shape-matching
        parties = [
            PartyFactory(slug=f"overlap{n:02d}-abcdef", name="Test Party")
            for n in range(1, 13)
        ]
        assert all(MINTED.fullmatch(p.slug) and len(p.slug) > 15 for p in parties)

        migration.re_mint_slugs(_RealApps(), None)

        slugs = [Party.objects.get(pk=p.pk).slug for p in parties]
        assert len(slugs) == len(set(slugs))  # unique across batches
        for slug in slugs:
            assert MINTED.fullmatch(slug), slug
            assert len(slug) <= 15

    def test_backfill_sets_osm_name_from_legacy_slug(self):
        # A row the migration state produces after the schema change:
        # legacy slug, empty extra (the factory default). The backfill
        # maps the slug — which WAS the normalized-name identity — into
        # ``extra.osm_name``.
        party = PartyFactory(slug="legacy_volg1", name="Coop Supermarkt")

        _migration().backfill_extra(_RealApps(), None)

        party.refresh_from_db()
        assert party.extra["osm_name"] == "legacy_volg1"

    def test_backfill_is_noop_when_identity_present(self):
        party = PartyFactory(name="Volg", extra={"osm_name": "volg"})

        _migration().backfill_extra(_RealApps(), None)

        party.refresh_from_db()
        assert party.extra == {"osm_name": "volg"}

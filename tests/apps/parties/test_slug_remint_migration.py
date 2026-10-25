"""parties 0003 re-mint migration tests.

The re-mint streams ``.only()`` rows, mints the 0054 shape
(``{base<=9}-{5 alnum}``), keeps the collision domain in a set and is
re-runnable: rows already matching the minted shape are excluded, so a
retried run finds nothing left to change. ``extra.osm_name`` values must
never move — they are the import identity.
"""

from __future__ import annotations

import importlib
import re
from typing import Any

import pytest

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
        assert party.slug.startswith("coopsupe-") or party.slug.split("-")[0]
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

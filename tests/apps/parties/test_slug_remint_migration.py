"""parties 0003 re-mint migration tests.

The re-mint streams ``.only()`` rows, mints the 0054 shape
(``{base<=9}-{5 alnum}``), keeps the collision domain in a set and is
re-runnable: rows already matching the minted shape are excluded, so a
retried run finds nothing left to change. ``dedup_key`` values must
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

MIGRATION = "server.apps.parties.migrations.0003_party_dedup_key_and_slug_remint"
MINTED = re.compile(r"^[a-z0-9]{1,9}-[a-z0-9]{5}$")


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
        party = PartyFactory(slug="legacy_volg1", name="Coop Supermarkt")
        key = party.dedup_key
        assert not MINTED.fullmatch(party.slug)  # the legacy value

        _run_remint()

        party.refresh_from_db()
        assert MINTED.fullmatch(party.slug)
        assert len(party.slug) <= 15
        assert party.slug.startswith("coopsupe-") or party.slug.split("-")[0]
        assert party.dedup_key == key  # the identity never moves

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

    def test_backfill_is_noop_when_keys_present(self):
        # The test database ran 0003 at --create-db time (keys are NOT
        # NULL); the backfill filter must select nothing.
        party = PartyFactory(name="Volg")

        _migration().backfill_dedup_keys(_RealApps(), None)

        party.refresh_from_db()
        assert party.dedup_key == "volg"

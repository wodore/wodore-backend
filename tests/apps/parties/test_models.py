"""Party model tests: minted slugs + dedup keys.

OpenSpec change ``party-slug-minting`` (task 2.1): ``slug`` is a short
public identifier minted once at creation (blank on save -> minted),
``extra.osm_name`` is the normalized-name import identity (written by the
blank. Both are unique; neither is ever re-derived once set.
"""

import re

import pytest

from tests.factories.parties import PartyFactory

from django.db import IntegrityError

from server.apps.parties.models import Party

pytestmark = pytest.mark.django_db

MINTED = re.compile(r"^[a-z0-9]{1,9}-[a-z0-9]{5,8}$")


class TestNormalizeKey:
    """``normalize_key`` is verbatim the OSM import's former
    ``_normalize_party_slug`` — re-imports must keep matching."""

    def test_lowercases_and_underscores(self):
        assert Party.normalize_key("SAC Bern") == "sac_bern"

    def test_no_length_trim(self):
        # ``extra`` JSONB carries the identity — no column limit to
        # trim to (review comment 1).
        assert Party.normalize_key("x" * 80) == "x" * 80

    def test_identity_for_owner_style_slugs(self):
        # Owner slugs (hyphenated, lowercase) pass through unchanged -
        # the owner merge keys on them.
        assert Party.normalize_key("sac-pilatus") == "sac-pilatus"


class TestSaveMinting:
    def test_slug_minted_when_blank(self):
        party = Party.objects.create(name="SAC Bern")
        assert MINTED.fullmatch(party.slug)
        assert len(party.slug) <= 15
        assert party.extra == {}  # save() never invents the import identity

    def test_explicit_slug_preserved(self):
        party = Party.objects.create(slug="volg", name="Volg")
        assert party.slug == "volg"
        assert party.extra == {}

    def test_import_identity_rides_extra(self):
        # The identity is written by the import paths, not by save().
        party = Party.objects.create(
            name="Coop Supermarkt", extra={"osm_name": "coop_supermarkt"}
        )
        assert party.extra["osm_name"] == "coop_supermarkt"
        assert MINTED.fullmatch(party.slug)

    def test_nameless_party_mints_from_extra(self):
        # No name, no slug: the ``extra.osm_name`` identity drives the
        # base, "party" is the last resort fallback.
        party = Party.objects.create(extra={"osm_name": "xyz_club"})
        assert party.slug.startswith("xyzclub-")

    def test_slug_and_extra_stable_on_resave(self):
        party = PartyFactory(name="Migros")
        slug, extra = party.slug, party.extra

        party.name = "Migros City"
        party.save()

        assert party.slug == slug  # minted once, never re-derived
        assert party.extra == extra  # the identity never moves

    def test_duplicate_slug_rejected(self):
        Party.objects.create(slug="volg", name="First")
        with pytest.raises(IntegrityError):
            Party.objects.create(slug="volg", name="Second")


class TestSlugCollisionRetry:
    """A unique collision on a freshly minted slug re-mints a new
    suffix and retries inside a savepoint (review comment 2)."""

    def test_collision_remints_and_retries(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        Party.objects.create(slug="aaaaa-11111", name="Existing")

        minted = iter(["aaaaa-11111", "bbbbb-22222"])

        def fake_mint(*_args: object, **_kwargs: object) -> str:
            return next(minted)

        monkeypatch.setattr(
            "server.apps.parties.models._party.mint_short_slug", fake_mint
        )

        party = Party.objects.create(name="Migros")

        assert party.slug == "bbbbb-22222"
        assert Party.objects.count() == 2

    def test_exhausted_retries_raise(self, monkeypatch: pytest.MonkeyPatch) -> None:
        Party.objects.create(slug="aaaaa-11111", name="Existing")

        def fake_mint(*_args: object, **_kwargs: object) -> str:
            return "aaaaa-11111"

        monkeypatch.setattr(
            "server.apps.parties.models._party.mint_short_slug", fake_mint
        )

        with pytest.raises(IntegrityError):
            Party.objects.create(name="Migros")


class TestSlugNotEmptyConstraint:
    """blank=True is form-level only; the database rejects empty slugs
    (review comment 3) — bulk_create bypasses save(), so the check
    constraint is what fires."""

    def test_bulk_create_empty_slug_rejected(self) -> None:
        with pytest.raises(IntegrityError):
            Party.objects.bulk_create([Party(slug="", name="No Slug")])

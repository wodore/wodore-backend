"""Tests for the owner merge into parties (tasks 3.1 and 3.2).

The test database is a dev clone (existing Owner/Hut rows) — all
assertions are scoped to factory-created slugs, and the commands are
expected to be idempotent against the clone data.
"""

import pytest

from tests.factories.huts import HutFactory
from tests.factories.owners import OwnerFactory

from django.core.management import call_command

from server.apps.external_links.models import ExternalLink
from server.apps.geometries.models import GeoPlace
from server.apps.parties.models import Party, PartyLink

pytestmark = pytest.mark.django_db


class TestImportParties:
    def test_merges_owner_with_url(self):
        owner = OwnerFactory(name="SAC Bern", url="https://sac-bern.example.com")

        call_command("import_parties")

        party = Party.objects.get(dedup_key=Party.normalize_key(owner.slug))
        assert party.name == "SAC Bern"
        assert party.slug != owner.slug  # minted short identifier, not the key
        association = party.link_associations.get()
        assert association.external_link.url == "https://sac-bern.example.com"

    def test_idempotent_rerun(self):
        owner = OwnerFactory(url="https://sac-bern.example.com")

        call_command("import_parties")
        first_slug = Party.objects.get(dedup_key=Party.normalize_key(owner.slug)).slug
        call_command("import_parties")

        assert (
            Party.objects.filter(dedup_key=Party.normalize_key(owner.slug)).count() == 1
        )
        # Minted once: the re-merge resolves through the key and never
        # re-derives the slug.
        assert (
            Party.objects.get(dedup_key=Party.normalize_key(owner.slug)).slug
            == first_slug
        )
        assert (
            PartyLink.objects.filter(
                party__dedup_key=Party.normalize_key(owner.slug)
            ).count()
            == 1
        )
        assert (
            ExternalLink.objects.filter(url="https://sac-bern.example.com").count() == 1
        )

    def test_dry_run_writes_nothing(self):
        owner = OwnerFactory(url="https://sac-bern.example.com")

        call_command("import_parties", "--dry-run")

        assert not Party.objects.filter(
            dedup_key=Party.normalize_key(owner.slug)
        ).exists()
        assert not ExternalLink.objects.filter(
            url="https://sac-bern.example.com"
        ).exists()


class TestWodoreHutImport:
    def test_hut_import_links_operator_party(self):
        owner = OwnerFactory(name="SAC Bern")
        hut = HutFactory(slug="party-test-hut", hut_owner=owner)

        call_command("import_geoplaces", sources="wodore")

        place = GeoPlace.objects.get(source_associations__source_id=hut.slug)
        association = place.party_associations.get()  # type: ignore  # reverse FK: plugin-less inference gap
        assert association.role.identifier == "role.operator"
        assert association.party.dedup_key == Party.normalize_key(owner.slug)


class TestOwnerProvisioningMigration:
    """The migrate-time merge (parties 0002) — ran on the test database
    during ``--create-db``; re-running must change nothing."""

    def test_every_owner_has_a_party(self):
        from server.apps.owners.models import Owner

        merged = Party.objects.filter(dedup_key__in=Owner.objects.values("slug"))
        assert merged.count() == Owner.objects.count()

    def test_migration_idempotent(self):
        import importlib

        from django.apps import apps as global_apps

        module = importlib.import_module(
            "server.apps.parties.migrations.0002_merge_owners_into_parties"
        )
        before = Party.objects.count()

        module.merge_owners(global_apps, None)

        assert Party.objects.count() == before

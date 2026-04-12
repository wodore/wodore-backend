"""Verification tests for the test seed infrastructure."""

import pytest

from server.apps.huts.models import Hut


@pytest.mark.django_db
class TestSeedFixture:
    """Verify seed data is loaded and accessible."""

    def test_huts_exist_in_db(self, seed_data):
        """Seed data should be loaded and huts should be present."""
        assert Hut.objects.exists(), "No huts found — seed data may not have loaded"
        assert (
            Hut.objects.count() >= 5
        ), f"Expected >= 5 huts, got {Hut.objects.count()}"

    def test_hut_has_required_fields(self, seed_data):
        """Each seeded hut should have name, location, elevation, etc."""
        hut = Hut.objects.first()
        assert hut.name, "Hut should have a name"
        assert hut.location, "Hut should have a location"
        assert hut.slug, "Hut slug should be auto-generated"
        assert hut.country_field, "Hut should have a country"
        assert hut.hut_type_open, "Hut should have hut_type_open"

    def test_hut_has_organizations(self, seed_data):
        """Seeded huts should have organization associations."""
        huts_with_orgs = 0
        for hut in Hut.objects.all():
            if hut.org_set.exists():
                huts_with_orgs += 1
        assert huts_with_orgs > 0, "Expected at least some huts with organizations"

    def test_hut_slug_is_unique(self, seed_data):
        """All hut slugs should be unique."""
        slugs = list(Hut.objects.values_list("slug", flat=True))
        assert len(slugs) == len(set(slugs)), "Duplicate slugs found"


@pytest.mark.django_db
class TestTransactionRollback:
    """Verify transaction rollback provides test isolation."""

    def test_delete_hut(self, seed_data):
        """Delete a hut within this test — it should be gone here."""
        hut = Hut.objects.first()
        assert hut is not None
        hut_id = hut.id
        hut.delete()
        assert not Hut.objects.filter(id=hut_id).exists()

    def test_hut_is_back(self, seed_data):
        """After previous test deleted a hut, it should be back (rollback)."""
        assert Hut.objects.exists(), "Huts should be back after transaction rollback"

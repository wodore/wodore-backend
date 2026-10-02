"""HTTP-level tests for the hut Markdown endpoint (/v1/huts/{slug}.md)."""

import pytest

from server.apps.huts.models import Hut
from server.apps.organizations.models import Organization

pytestmark = [pytest.mark.django_db]


@pytest.fixture(autouse=True)
def _frontend_domain(settings):
    settings.FRONTEND_DOMAIN = "https://wodore.com"


class TestHutMarkdown:
    def test_markdown_detail(self, seed_data, client):
        hut = Hut.objects.filter(is_active=True, is_public=True).first()
        assert hut is not None
        response = client.get(f"/v1/huts/{hut.slug}.md")
        assert response.status_code == 200
        assert response.headers["Content-Type"].startswith("text/markdown")
        assert "public, max-age=" in response.headers["Cache-Control"]

        body = response.content.decode()
        assert f"# {hut.name}" in body
        assert "## Overview" in body
        assert "## Open months" in body
        assert "## Description" in body
        assert "## Sources" in body
        # Links for agents: back to the app and to the JSON source.
        assert f"https://wodore.com/hut/{hut.slug}" in body
        assert f"/v1/huts/{hut.slug}" in body
        # Last-updated footer from the modified timestamp.
        assert f"Last updated: {hut.modified:%Y-%m-%d}" in body

    def test_markdown_keeps_attribution(self, seed_data, client):
        hut = (
            Hut.objects.filter(
                is_active=True, is_public=True, description_attribution__contains="href"
            ).first()
            or Hut.objects.filter(is_active=True, is_public=True).first()
        )
        assert hut is not None
        response = client.get(f"/v1/huts/{hut.slug}.md")
        assert response.status_code == 200
        body = response.content.decode()
        if hut.description_attribution:
            # HTML anchors become Markdown links; no raw HTML tags remain.
            assert "<a href" not in body
            assert "*Description:" in body

    def test_markdown_unknown_slug_is_404(self, seed_data, client):
        response = client.get("/v1/huts/does-not-exist-xyz.md")
        assert response.status_code == 404

    def test_markdown_hidden_hut_is_404(self, seed_data, client):
        hut = Hut.objects.filter(is_active=True, is_public=True).first()
        assert hut is not None
        hut.is_public = False
        hut.save()
        response = client.get(f"/v1/huts/{hut.slug}.md")
        assert response.status_code == 404

    def test_markdown_links_live_availability_when_sourced(self, seed_data, client):
        """Huts with an availability source link the live availability API."""
        hut = Hut.objects.filter(
            is_active=True, is_public=True, availability_source_ref=None
        ).first()
        assert hut is not None
        org = Organization.objects.first()
        if org is None:
            org = Organization.objects.create(
                slug="test-avail-org", name="Test Avail Org"
            )
        hut.availability_source_ref = org
        hut.save()
        try:
            body = client.get(f"/v1/huts/{hut.slug}.md").content.decode()
            assert "Live bed availability (JSON):" in body
            assert f"/v1/huts/{hut.slug}/availability/today?days=7" in body
        finally:
            # Session-scoped seed DB: leave the hut unsourced again.
            hut.availability_source_ref = None
            hut.save()

    def test_markdown_without_availability_source_has_no_link(self, seed_data, client):
        hut = Hut.objects.filter(
            is_active=True, is_public=True, availability_source_ref=None
        ).first()
        assert hut is not None
        body = client.get(f"/v1/huts/{hut.slug}.md").content.decode()
        assert "availability/today" not in body

    def test_json_detail_still_works_for_same_slug(self, seed_data, client):
        """The /{slug} catch-all must not swallow or break .md handling."""
        hut = Hut.objects.filter(is_active=True, is_public=True).first()
        assert hut is not None
        assert client.get(f"/v1/huts/{hut.slug}").status_code == 200
        assert client.get(f"/v1/huts/{hut.slug}.md").status_code == 200

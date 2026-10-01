"""HTTP-level tests for the hut Markdown endpoint (/v1/huts/{slug}.md)."""

import pytest

from server.apps.huts.models import Hut

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

    def test_json_detail_still_works_for_same_slug(self, seed_data, client):
        """The /{slug} catch-all must not swallow or break .md handling."""
        hut = Hut.objects.filter(is_active=True, is_public=True).first()
        assert hut is not None
        assert client.get(f"/v1/huts/{hut.slug}").status_code == 200
        assert client.get(f"/v1/huts/{hut.slug}.md").status_code == 200

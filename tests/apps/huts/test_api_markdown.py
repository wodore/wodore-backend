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


class TestHutMarkdownSeasons:
    def test_months_show_both_modes_with_explanation(self, seed_data, client):
        hut = Hut.objects.filter(
            is_active=True, is_public=True, hut_type_closed__isnull=False
        ).first()
        assert hut is not None, "seed data must contain a hut with reduced operation"
        body = client.get(f"/v1/huts/{hut.slug}.md").content.decode()
        # Labeled rows for both service levels, named by their category.
        assert f"| Standard ({hut.hut_type_open.name}) |" in body
        assert f"| Reduced ({hut.hut_type_closed.name}) |" in body
        # Value legend and the derivation disclaimer for the reduced row.
        assert "Legend: yes = open" in body
        assert "Reduced-operation months are derived" in body

    def test_months_standard_only_without_reduced_type(self, seed_data, client):
        hut = Hut.objects.filter(
            is_active=True, is_public=True, hut_type_closed__isnull=True
        ).first()
        if hut is None:
            pytest.skip("seed has no hut without reduced operation")
        body = client.get(f"/v1/huts/{hut.slug}.md").content.decode()
        assert f"| Standard ({hut.hut_type_open.name}) |" in body
        assert "| Reduced (" not in body
        assert "No reduced operation (e.g. winter room) is recorded" in body

    def test_reduced_row_derives_yes_from_closed_standard_months(
        self, seed_data, client
    ):
        hut = Hut.objects.filter(
            is_active=True, is_public=True, hut_type_closed__isnull=False
        ).first()
        assert hut is not None
        open_monthly = {
            f"month_{m:02d}": ("yes" if m in (7, 8) else "no") for m in range(1, 13)
        }
        hut.open_monthly = open_monthly
        hut.save()
        body = client.get(f"/v1/huts/{hut.slug}.md").content.decode()
        standard_row = body.split(f"| Standard ({hut.hut_type_open.name}) |")[1]
        reduced_row = body.split(f"| Reduced ({hut.hut_type_closed.name}) |")[1]
        std_months = [c.strip() for c in standard_row.split("|")[:13]]
        red_months = [c.strip() for c in reduced_row.split("|")[:13]]
        assert std_months[6] == "yes" and std_months[0] == "no"
        assert red_months[6] == "-"  # full service months: reduced n/a
        assert red_months[0] == "yes\\*"  # closed months: reduced self-access


class TestHutMarkdownNearby:
    def test_nearby_huts_listed_with_distance(self, seed_data, client):
        from django.contrib.gis.geos import Point

        huts = list(Hut.objects.filter(is_active=True, is_public=True)[:2])
        assert len(huts) == 2, "seed data must contain at least two huts"
        hut, other = huts
        assert hut.location is not None
        # Place the second hut 3 km east of the first, inside the radius.
        other.location = Point(hut.location.x + 0.04, hut.location.y)
        other.save()
        body = client.get(f"/v1/huts/{hut.slug}.md").content.decode()
        assert "## Nearby huts" in body
        assert "within 15 km" in body
        # Entry with distance and a link to the other hut's app page.
        assert f"[{other.name}](https://wodore.com/hut/{other.slug})" in body
        assert " — 3." in body

    def test_no_nearby_section_when_isolated(self, seed_data, client):
        from django.contrib.gis.geos import Point

        hut = Hut.objects.filter(is_active=True, is_public=True).first()
        assert hut is not None
        hut.location = Point(0.0, 0.0)  # far from any seeded hut
        hut.save()
        body = client.get(f"/v1/huts/{hut.slug}.md").content.decode()
        assert "## Nearby huts" not in body

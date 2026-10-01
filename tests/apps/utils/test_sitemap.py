"""HTTP-level tests for the XML sitemap endpoints.

The sitemap is generated from the public hut surface and must mirror it:
only ``is_active=True, is_public=True`` huts, as absolute URLs on the
frontend host (``FRONTEND_DOMAIN``), reachable from the sitemap index
that the frontend nginx proxies to ``/v1/sitemap.xml``.
"""

import pytest

from server.apps.api.sitemap import SITEMAP_PAGE_SIZE
from server.apps.huts.models import Hut

pytestmark = [pytest.mark.django_db]


@pytest.fixture(autouse=True)
def _frontend_domain(settings):
    settings.FRONTEND_DOMAIN = "https://wodore.com"


@pytest.fixture(autouse=True)
def _clear_sitemap_cache():
    from django.core.cache import cache

    for key in [
        "sitemap:index",
        "sitemap:static",
        "sitemap:huts:count",
        *[f"sitemap:huts:{page}" for page in range(10)],
    ]:
        cache.delete(key)
    yield
    for key in [
        "sitemap:index",
        "sitemap:static",
        "sitemap:huts:count",
        *[f"sitemap:huts:{page}" for page in range(10)],
    ]:
        cache.delete(key)


class TestSitemapIndex:
    def test_index_is_valid_xml(self, seed_data, client):
        response = client.get("/v1/sitemap.xml")
        assert response.status_code == 200
        assert response.headers["Content-Type"].startswith("application/xml")
        assert b"<sitemapindex" in response.content
        assert b"https://wodore.com/sitemap-static.xml" in response.content
        # At least one hut page is referenced.
        assert b"https://wodore.com/sitemap-huts-0.xml" in response.content

    def test_index_lists_every_page(self, seed_data, client, monkeypatch):
        monkeypatch.setattr("server.apps.api.sitemap.SITEMAP_PAGE_SIZE", 2)
        public_huts = Hut.objects.filter(is_active=True, is_public=True).count()
        expected_pages = max(1, -(-public_huts // 2))
        response = client.get("/v1/sitemap.xml")
        assert response.status_code == 200
        for page in range(expected_pages):
            assert (
                f"https://wodore.com/sitemap-huts-{page}.xml".encode()
                in response.content
            )


class TestSitemapStatic:
    def test_static_pages(self, seed_data, client):
        response = client.get("/v1/sitemap-static.xml")
        assert response.status_code == 200
        assert b"<urlset" in response.content
        assert b"<loc>https://wodore.com/</loc>" in response.content
        assert b"<loc>https://wodore.com/data-policy</loc>" in response.content


class TestSitemapHuts:
    def test_huts_page_lists_public_huts(self, seed_data, client):
        response = client.get("/v1/sitemap-huts-0.xml")
        assert response.status_code == 200
        assert b"<urlset" in response.content

        public_huts = Hut.objects.filter(is_active=True, is_public=True)
        first = public_huts.order_by("pk").first()
        assert first is not None
        assert (
            f"<loc>https://wodore.com/hut/{first.slug}</loc>".encode()
            in response.content
        )
        # Every public hut appears on page 0 when they fit one page.
        assert public_huts.count() <= SITEMAP_PAGE_SIZE
        assert response.content.count(b"<url>") == public_huts.count()

    def test_hidden_huts_are_excluded(self, seed_data, client):
        hidden = (
            Hut.objects.filter(is_active=True, is_public=True).order_by("pk").first()
        )
        assert hidden is not None
        hidden.is_public = False
        hidden.save()

        from django.core.cache import cache

        cache.delete("sitemap:huts:0")

        response = client.get("/v1/sitemap-huts-0.xml")
        assert response.status_code == 200
        assert f"https://wodore.com/hut/{hidden.slug}".encode() not in response.content

    def test_out_of_range_page_is_404(self, seed_data, client):
        response = client.get("/v1/sitemap-huts-9999.xml")
        assert response.status_code == 404

    def test_negative_page_is_404(self, seed_data, client):
        response = client.get("/v1/sitemap-huts--1.xml")
        assert response.status_code == 404

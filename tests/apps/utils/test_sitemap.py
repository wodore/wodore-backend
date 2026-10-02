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


class TestSitemapPlaces:
    @pytest.fixture(autouse=True)
    def _clear_places_cache(self):
        from django.core.cache import cache

        for key in [
            "sitemap:index",
            "sitemap:places:count",
            "sitemap:category-include-ids",
            *[f"sitemap:places:{p_}" for p_ in range(10)],
        ]:
            cache.delete(key)
        yield
        for key in [
            "sitemap:index",
            "sitemap:places:count",
            "sitemap:category-include-ids",
            *[f"sitemap:places:{p_}" for p_ in range(10)],
        ]:
            cache.delete(key)

    @pytest.fixture
    def include_category(self):
        from server.apps.categories.models import Category

        return Category.objects.create(
            slug="seo-include-test",
            name="SEO Include",
            seo_sitemap=Category.SeoSitemapChoices.include,
        )

    def _clear(self):
        from django.core.cache import cache

        cache.delete("sitemap:index")
        cache.delete("sitemap:places:count")
        cache.delete("sitemap:category-include-ids")

    def test_disabled_by_default(self, seed_data, client):
        response = client.get("/v1/sitemap.xml")
        assert b"sitemap-places" not in response.content
        assert client.get("/v1/sitemap-places-0.xml").status_code == 404

    def test_enabled_lists_places_with_name_and_include_category(
        self, seed_data, client, settings, include_category
    ):
        settings.WODORE_SEO_PLACE_SITEMAP = True
        from server.apps.geometries.models import GeoPlace

        place = GeoPlace.objects.filter(is_active=True, is_public=True).first()
        assert place is not None
        place.name = "Testplace"
        place.description = ""  # description no longer required
        place.categories.add(include_category)
        self._clear()

        assert b"sitemap-places-0.xml" in client.get("/v1/sitemap.xml").content
        page = client.get("/v1/sitemap-places-0.xml")
        assert page.status_code == 200
        assert place.slug.encode() in page.content

    def test_nameless_place_excluded(
        self, seed_data, client, settings, include_category
    ):
        settings.WODORE_SEO_PLACE_SITEMAP = True
        from server.apps.geometries.models import GeoPlace

        place = (
            GeoPlace.objects.filter(is_active=True, is_public=True)
            .exclude(name="")
            .first()
        )
        assert place is not None
        place.categories.add(include_category)
        place.name = ""
        place.save()
        self._clear()
        page = client.get("/v1/sitemap-places-0.xml")
        assert place.slug.encode() not in page.content

    def test_category_without_include_flag_excludes_places(
        self, seed_data, client, settings
    ):
        """Tri-state: categories default to exclude (root None)."""
        settings.WODORE_SEO_PLACE_SITEMAP = True
        from server.apps.categories.models import Category
        from server.apps.geometries.models import GeoPlace

        category = Category.objects.create(slug="seo-none-test", name="No Flag")
        place = GeoPlace.objects.filter(is_active=True, is_public=True).first()
        assert place is not None
        place.name = "Flagless"
        place.save()
        place.categories.add(category)
        self._clear()
        page = client.get("/v1/sitemap-places-0.xml")
        assert place.slug.encode() not in page.content

    def test_category_tri_state_inheritance(
        self, seed_data, client, settings, include_category
    ):
        """Child with no value inherits the parent's include; explicit
        exclude on the child wins over the parent's include."""
        settings.WODORE_SEO_PLACE_SITEMAP = True
        from server.apps.categories.models import Category
        from server.apps.geometries.models import GeoPlace

        inheriting_child = Category.objects.create(
            slug="seo-child-inherit", name="Child", parent=include_category
        )
        excluded_child = Category.objects.create(
            slug="seo-child-exclude",
            name="Excluded Child",
            parent=include_category,
            seo_sitemap=Category.SeoSitemapChoices.exclude,
        )

        listed = GeoPlace.objects.filter(is_active=True, is_public=True)[0]
        listed.name = "Listed Place"
        listed.save()
        listed.categories.add(inheriting_child)

        excluded = GeoPlace.objects.filter(is_active=True, is_public=True)[1]
        excluded.name = "Excluded Place"
        excluded.save()
        excluded.categories.add(excluded_child)

        self._clear()
        page = client.get("/v1/sitemap-places-0.xml")
        assert listed.slug.encode() in page.content
        assert excluded.slug.encode() not in page.content

    def test_effective_seo_sitemap_resolution(self, seed_data, include_category):
        from server.apps.categories.models import Category

        # Root without value -> None (callers treat as exclude)
        root = Category.objects.create(slug="seo-plain-root", name="Root")
        assert root.effective_seo_sitemap() is None
        # Child of include-root inherits include
        child = Category.objects.create(
            slug="seo-plain-child", name="Child", parent=include_category
        )
        assert child.effective_seo_sitemap() == Category.SeoSitemapChoices.include
        # Grandchild of excluded child stays excluded
        excluded_child = Category.objects.create(
            slug="seo-exc-child",
            name="Exc",
            parent=root,
            seo_sitemap=Category.SeoSitemapChoices.exclude,
        )
        grandchild = Category.objects.create(
            slug="seo-grandchild", name="GC", parent=excluded_child
        )
        assert grandchild.effective_seo_sitemap() == Category.SeoSitemapChoices.exclude


class TestHreflangAlternates:
    def test_hut_urls_carry_alternates(self, seed_data, client):
        from django.conf import settings
        from django.core.cache import cache

        from server.apps.api.sitemap import DEFAULT_LANG, LANG_PREFIXES

        cache.delete("sitemap:huts:0")
        response = client.get("/v1/sitemap-huts-0.xml")
        assert response.status_code == 200
        body = response.content.decode()
        assert 'xmlns:xhtml="http://www.w3.org/1999/xhtml"' in body
        # Derived from the lang config, not hardcoded lists.
        assert DEFAULT_LANG == settings.DEFAULT_LANG == "en"
        assert LANG_PREFIXES == (
            "de",
            "fr",
            "it",
        )
        for lang in (DEFAULT_LANG, *LANG_PREFIXES, "x-default"):
            assert f'hreflang="{lang}"' in body
        hut = Hut.objects.filter(is_active=True, is_public=True).order_by("pk").first()
        # Prefixed variants exist for every non-default language, and the
        # bare <loc> is the default language.
        for lang in LANG_PREFIXES:
            assert f"https://wodore.com/{lang}/hut/{hut.slug}" in body
        assert f"https://wodore.com/hut/{hut.slug}</loc>" in body
        assert f"https://wodore.com/{DEFAULT_LANG}/hut/{hut.slug}" not in body

    def test_static_pages_no_alternates(self, seed_data, client):
        from django.core.cache import cache

        cache.delete("sitemap:static")
        response = client.get("/v1/sitemap-static.xml")
        assert response.status_code == 200
        assert b"hreflang" not in response.content

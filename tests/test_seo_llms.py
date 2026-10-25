"""HTTP-level tests for the LLM/SEO surfaces: llms.txt and robots.txt.

robots.txt is environment-aware: production additionally allows
well-behaved AI crawlers on the public read-only endpoints, every other
environment (staging/preview/test) denies everything.

llms.txt is environment-aware as well: production serves the full
document built from the request host, while staging leads with a notice
pointing LLM readers at production and advertises production URLs only.
Every llms.txt URL is language-fixed — the bare root is always English,
German/French/Italian live at /llms.<lang>.txt — so responses carry an
explicit Cache-Control and no Vary: the CDN does not vary on
Accept-Language.
"""

import pytest
from pytest_django.fixtures import SettingsWrapper

from django.test import Client

pytestmark = [pytest.mark.django_db]


@pytest.fixture(autouse=True)
def _frontend_domain(settings: SettingsWrapper):
    settings.FRONTEND_DOMAIN = "https://wodore.com"


# Per-language llms.txt variants; the bare /llms.txt is the English one.
LLMS_VARIANTS = {"de": "/llms.de.txt", "fr": "/llms.fr.txt", "it": "/llms.it.txt"}
ALL_LLMS_PATHS = ("/llms.txt", *LLMS_VARIANTS.values())


class TestLlmsTxt:
    def test_llms_txt_is_markdown_entry_point(self, client: Client):
        response = client.get("/llms.txt")
        assert response.status_code == 200
        assert response.headers["Content-Type"].startswith("text/plain")
        body = response.content.decode()
        assert body.startswith("# Wodore")
        # Key links for agents: app, markdown hut documents, sitemap.
        assert "https://wodore.com/hut/{slug}" in body
        assert "/v1/huts/{slug}.md" in body
        assert "https://wodore.com/hut/{slug}.md" in body
        assert "https://wodore.com/sitemap.xml" in body
        assert "OpenAPI" in body
        # Discovery pointers: name search, coordinates, live availability.
        assert "/v1/huts/search?q=rotond" in body
        assert "/v1/huts/huts.geojson" in body
        assert "/v1/huts/huts.geojson?bbox=7.6,45.9,8.1,46.2" in body
        assert "/v1/huts/{slug}/availability/today?days=7" in body
        assert "/v1/huts/availability/weekend.geojson" in body

    def test_llms_txt_uses_request_host(self, client: Client):
        response = client.get("/llms.txt")
        assert response.status_code == 200
        body = response.content.decode()
        # Built from the request host, not hardcoded — staging serves
        # staging links.
        assert "http://testserver/v1/huts/huts" in body

    def test_llms_txt_staging_leads_with_notice_and_advertises_production_only(
        self,
        client: Client,
        settings: SettingsWrapper,
        monkeypatch: pytest.MonkeyPatch,
    ):
        # A staging deploy has a staging FRONTEND_DOMAIN and receives
        # staging request hosts — llms.txt must advertise neither.
        settings.FRONTEND_DOMAIN = "https://stg.wodore.com"
        settings.ALLOWED_HOSTS = ["*"]
        monkeypatch.setenv("DJANGO_ENV", "staging")
        response = client.get("/llms.txt", headers={"host": "stg-api.wodore.com"})
        assert response.status_code == 200
        assert response.headers["Content-Type"].startswith("text/plain")
        body = response.content.decode()
        # Leads with the staging notice pointing LLM readers at
        # production and its llms.txt.
        assert body.startswith("# Wodore (staging)")
        assert "incomplete" in body
        assert "https://wodore.com/llms.txt" in body
        # The document body survives, but every advertised URL is the
        # production one — API links included.
        assert "https://wodore.com/v1/huts/huts" in body
        assert "https://wodore.com/hut/{slug}.md" in body
        assert "https://wodore.com/sitemap.xml" in body
        # Never a staging URL: not the request host, not FRONTEND_DOMAIN.
        assert "stg.wodore.com" not in body
        assert "stg-api.wodore.com" not in body

    def test_llms_txt_root_is_always_english(self, client: Client):
        """The bare /llms.txt is the entry point LLMs fetch by convention:
        always English, byte-identical regardless of Accept-Language."""
        default = client.get("/llms.txt")
        german = client.get("/llms.txt", headers={"accept-language": "de-DE,de;q=0.9"})
        assert default.status_code == german.status_code == 200
        assert default.content == german.content
        assert default.headers["Content-Language"] == "en"
        assert german.headers["Content-Language"] == "en"
        assert default.content.decode().startswith("# Wodore\n")

    def test_llms_txt_explicit_cache_headers_without_vary(self, client: Client):
        """Every llms.txt URL is language-fixed: explicit Cache-Control
        for the CDN, and no Vary (the CDN does not vary on
        Accept-Language — a Vary there would only split or confuse)."""
        for path in ALL_LLMS_PATHS:
            response = client.get(path, headers={"accept-language": "fr-FR,fr;q=0.9"})
            assert response.status_code == 200, path
            assert (
                response.headers["Cache-Control"]
                == "public, max-age=3600, stale-while-revalidate=86400"
            ), path
            assert "Vary" not in response.headers, path

    def test_vary_stripping_is_scoped_to_llms_paths(self, client: Client):
        """Only the llms.txt documents are made negotiation-free — other
        pages keep the Vary: Accept-Language LocaleMiddleware adds."""
        response = client.get("/")
        assert "Accept-Language" in response.headers.get("Vary", "")

    def test_llms_txt_root_cross_links_variants(self, client: Client):
        """The English root opens its header block with links to every
        language variant (stable per-language URLs for LLM crawlers)."""
        response = client.get("/llms.txt")
        assert response.status_code == 200
        body = response.content.decode()
        assert body.startswith("# Wodore\n> Other languages: ")
        for variant in LLMS_VARIANTS.values():
            assert f"https://wodore.com{variant}" in body

    def test_llms_variants_cross_link_other_languages(self, client: Client):
        """Each variant links every OTHER language — the English root and
        the sibling variants, never itself — and keeps the full English
        document (no translations wired yet; the URLs are the stable
        per-language homes)."""
        for lang, path in LLMS_VARIANTS.items():
            response = client.get(path)
            assert response.status_code == 200, path
            assert response.headers["Content-Type"].startswith("text/plain")
            assert response.headers["Content-Language"] == "en"
            body = response.content.decode()
            # Same English document as the root, modulo the links line.
            assert body.startswith("# Wodore\n> Other languages: ")
            assert "https://wodore.com/llms.txt" in body
            # API links still follow the request host (non-staging).
            assert "http://testserver/v1/huts/huts" in body
            for other_lang, other_path in LLMS_VARIANTS.items():
                if other_lang == lang:
                    assert f"https://wodore.com{other_path}" not in body
                else:
                    assert f"https://wodore.com{other_path}" in body

    def test_llms_unknown_language_variant_is_404(self, client: Client):
        """No invented variants: only the routed languages exist."""
        for path in ("/llms.es.txt", "/llms.rm.txt", "/llms.en.txt"):
            assert client.get(path).status_code == 404, path

    def test_llms_variants_staging_advertise_production_only(
        self,
        client: Client,
        settings: SettingsWrapper,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Every variant keeps the #417 staging behavior: staging notice
        first, then only production URLs — language links included."""
        settings.FRONTEND_DOMAIN = "https://stg.wodore.com"
        settings.ALLOWED_HOSTS = ["*"]
        monkeypatch.setenv("DJANGO_ENV", "staging")
        for path in ALL_LLMS_PATHS:
            response = client.get(path, headers={"host": "stg-api.wodore.com"})
            assert response.status_code == 200, path
            body = response.content.decode()
            # Leads with the staging notice pointing LLM readers at
            # production and its llms.txt (language links come first,
            # the existing notice follows unchanged).
            assert body.startswith("# Wodore (staging)")
            assert "incomplete" in body
            assert "https://wodore.com/llms.txt" in body
            # Production URLs everywhere — API links included.
            assert "https://wodore.com/v1/huts/huts" in body
            assert "https://wodore.com/hut/{slug}.md" in body
            assert "https://wodore.com/sitemap.xml" in body
            # Language links point at the production variants too.
            for other_path in ALL_LLMS_PATHS:
                if other_path != path:
                    assert f"https://wodore.com{other_path}" in body, (path, other_path)
            # Never a staging URL: not the request host, not FRONTEND_DOMAIN.
            assert "stg.wodore.com" not in body
            assert "stg-api.wodore.com" not in body


class TestRobotsTxt:
    def test_non_production_denies_everything(self, client: Client):
        response = client.get("/robots.txt")
        assert response.status_code == 200
        body = response.content.decode()
        assert "User-agent: *\nDisallow: /" in body
        assert "GPTBot" not in body

    def test_production_allows_ai_crawlers_on_public_data(
        self, client: Client, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("DJANGO_ENV", "production")
        response = client.get("/robots.txt")
        assert response.status_code == 200
        body = response.content.decode()
        # The default group still denies everything for search engines.
        assert "User-agent: *\nDisallow: /" in body
        # AI crawler group allows only the public read-only surface.
        assert "User-agent: GPTBot" in body
        assert "User-agent: ClaudeBot" in body
        assert "User-agent: PerplexityBot" in body
        assert "Allow: /v1/huts/" in body
        assert "Allow: /llms.txt" in body
        # The per-language llms.txt variants are crawlable too.
        assert "Allow: /llms.de.txt" in body
        assert "Allow: /llms.fr.txt" in body
        assert "Allow: /llms.it.txt" in body
        assert "Allow: /admin" not in body

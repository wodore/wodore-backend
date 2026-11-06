"""HTTP-level tests for the LLM/SEO surfaces: llms.txt and robots.txt.

robots.txt is environment-aware: production additionally allows
well-behaved AI crawlers on the public read-only endpoints, every other
environment (staging/preview/test) denies everything.

llms.txt is environment-aware as well: production serves the full
document built from the request host, while staging leads with a notice
pointing LLM readers at production and advertises production URLs only.
Every llms.txt URL is language-fixed — the bare root is always English,
the other languages from settings.LANGUAGES live at /llms.<lang>.txt —
so responses carry an explicit Cache-Control and no Vary: the CDN does
not vary on Accept-Language.

The variant bodies are localized through the standard Django gettext
pipeline ({% translate %} in the template, locale/<lang>/ catalogs;
compilemessages runs in CI and the image build): the variant's locale
drives both the body and the Content-Language header. settings.LANGUAGES
is the single source of truth for the whole family — routes, cross-links,
robots.txt Allow lines and the language enumerations inside the body all
derive from it.
"""

import pytest
from pytest_django.fixtures import SettingsWrapper

from django.test import Client
from django.urls import resolve

from server.apps.main.views import LLMS_ROOT_LANG, llms_txt, llms_txt_redirect

pytestmark = [pytest.mark.django_db]


@pytest.fixture(autouse=True)
def _frontend_domain(settings: SettingsWrapper):
    settings.FRONTEND_DOMAIN = "https://wodore.com"


# Per-language llms.txt variants; the bare /llms.txt is the English one.
LLMS_VARIANTS = {"de": "/llms.de.txt", "fr": "/llms.fr.txt", "it": "/llms.it.txt"}
ALL_LLMS_PATHS = ("/llms.txt", *LLMS_VARIANTS.values())

# Localized markers (headings from locale/<lang>/LC_MESSAGES/django.po):
# one per variant language, absent from the other languages' documents.
LOCALIZED_MARKERS = {
    "de": "Hütten finden",
    "fr": "Trouver des cabanes",
    "it": "Trovare le capanne",
}


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


class TestLlmsVariants:
    def test_variants_serve_localized_body_and_content_language(self, client: Client):
        """Each variant renders its body in the URL's language (gettext
        catalog), with Content-Language matching — URLs and URL patterns
        stay untouched by the translation."""
        for lang, path in LLMS_VARIANTS.items():
            response = client.get(path, headers={"accept-language": "en-US,en;q=0.9"})
            assert response.status_code == 200, path
            assert response.headers["Content-Type"].startswith("text/plain")
            assert response.headers["Content-Language"] == lang, path
            body = response.content.decode()
            # Localized descriptive text (the localized heading) ...
            assert LOCALIZED_MARKERS[lang] in body, path
            # ... and no other language's marker, and no English one.
            for other_lang, marker in LOCALIZED_MARKERS.items():
                if other_lang != lang:
                    assert marker not in body, path
            assert "Finding huts" not in body, path
            # The URL surface is identical in every language: hut-page
            # pattern and API links keep their shape and placeholders.
            assert "https://wodore.com/{lang}/hut/{slug}" in body
            assert "/v1/huts/{slug}.md" in body
            assert "http://testserver/v1/huts/huts" in body
            assert "http://testserver/v1/huts/{slug}?lang=de|en|fr|it" in body
            assert "https://wodore.com/hut/{slug}.md?lang=de|en|fr|it" in body, path
            # Byte-stable per URL: Accept-Language must not leak in.
            other = client.get(path, headers={"accept-language": "it-IT,it;q=0.9"})
            assert other.content == response.content, path

    def test_variants_cross_link_other_languages(self, client: Client):
        """Each variant links every OTHER language — the English root and
        the sibling variants, never itself — labeled with the native
        language names, regardless of the variant's own language."""
        native_names = {"de": "Deutsch", "fr": "Français", "it": "Italiano"}
        for lang, path in LLMS_VARIANTS.items():
            response = client.get(path)
            assert response.status_code == 200, path
            body = response.content.decode()
            # The localized "Other languages" label opens the links line.
            assert body.startswith("# Wodore\n> "), path
            assert "https://wodore.com/llms.txt" in body
            for other_lang, other_path in LLMS_VARIANTS.items():
                if other_lang == lang:
                    assert f"https://wodore.com{other_path}" not in body
                else:
                    assert (
                        f"{native_names[other_lang]}: https://wodore.com{other_path}"
                        in body
                    )


class TestLlmsUnknownLanguage:
    def test_unknown_language_variant_redirects_permanently_to_root(
        self, client: Client
    ):
        """No invented variants 404: unknown languages — and the root
        language under its variant spelling — land on a 301 to the
        canonical English entry point (GET-only documents: 301 is the
        Django convention, nothing to preserve for POST)."""
        for path in ("/llms.es.txt", "/llms.rm.txt", "/llms.en.txt", "/llms.xx.txt"):
            response = client.get(path)
            assert response.status_code == 301, path
            assert response.headers["Location"] == "/llms.txt", path
            # Redirects are as cacheable as the documents themselves.
            assert "Vary" not in response.headers, path
            assert (
                response.headers["Cache-Control"]
                == "public, max-age=3600, stale-while-revalidate=86400"
            ), path


class TestLlmsSettingsDriven:
    """settings.LANGUAGES is the single source of truth: one place to add
    a language — routes, cross-links, robots Allow lines and the body's
    language enumerations all follow it."""

    def test_urlconf_routes_follow_settings_languages(self):
        """Every non-root language in settings.LANGUAGES has its explicit
        variant route to the serving view; the catch-all handles the
        rest (permanently redirecting unknown spellings)."""
        from django.conf import settings

        for code, _name in settings.LANGUAGES:
            match = resolve(
                f"/llms.{code}.txt" if code != LLMS_ROOT_LANG else "/llms.txt"
            )
            assert match.func is llms_txt
        match = resolve("/llms.zz.txt")
        assert match.func is llms_txt_redirect

    def test_new_language_in_settings_serves_without_other_changes(
        self, client: Client, settings: SettingsWrapper
    ):
        """Adding a language to settings.LANGUAGES alone lights up its
        variant (the body falls back to the English msgid until a
        catalog exists — Content-Language still names the variant)."""
        settings.LANGUAGES = (*settings.LANGUAGES, ("es", "Spanish"))
        response = client.get("/llms.es.txt")
        assert response.status_code == 200
        assert response.headers["Content-Language"] == "es"
        body = response.content.decode()
        # The language enumerations inside the body follow settings too.
        assert "?lang=de|en|fr|it|es" in body

    def test_robots_allow_lines_follow_settings_languages(
        self, client: Client, monkeypatch: pytest.MonkeyPatch, settings: SettingsWrapper
    ):
        monkeypatch.setenv("DJANGO_ENV", "production")
        settings.LANGUAGES = (*settings.LANGUAGES, ("es", "Spanish"))
        response = client.get("/robots.txt")
        assert response.status_code == 200
        body = response.content.decode()
        assert "Allow: /llms.txt" in body
        for path in (*LLMS_VARIANTS.values(), "/llms.es.txt"):
            assert f"Allow: {path}" in body


class TestLlmsStaging:
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

    def test_variants_staging_advertise_production_only_in_every_language(
        self,
        client: Client,
        settings: SettingsWrapper,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Every variant keeps the #417 staging behavior, localized: the
        translated staging notice first, then only production URLs —
        language links included."""
        settings.FRONTEND_DOMAIN = "https://stg.wodore.com"
        settings.ALLOWED_HOSTS = ["*"]
        monkeypatch.setenv("DJANGO_ENV", "staging")
        staging_notices = {
            "de": "Staging-Umgebung",
            "fr": "Environnement de staging",
            "it": "Ambiente di staging",
        }
        for lang, path in LLMS_VARIANTS.items():
            response = client.get(path, headers={"host": "stg-api.wodore.com"})
            assert response.status_code == 200, path
            assert response.headers["Content-Language"] == lang, path
            body = response.content.decode()
            # Leads with the localized staging notice pointing LLM
            # readers at production and its llms.txt.
            assert body.startswith("# Wodore (staging)")
            assert staging_notices[lang] in body, path
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
        for variant in LLMS_VARIANTS.values():
            assert f"Allow: {variant}" in body
        assert "Allow: /admin" not in body

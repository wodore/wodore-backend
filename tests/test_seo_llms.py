"""HTTP-level tests for the LLM/SEO surfaces: llms.txt and robots.txt.

robots.txt is environment-aware: production additionally allows
well-behaved AI crawlers on the public read-only endpoints, every other
environment (staging/preview/test) denies everything.
"""

import pytest

pytestmark = [pytest.mark.django_db]


@pytest.fixture(autouse=True)
def _frontend_domain(settings):
    settings.FRONTEND_DOMAIN = "https://wodore.com"


class TestLlmsTxt:
    def test_llms_txt_is_markdown_entry_point(self, client):
        response = client.get("/llms.txt")
        assert response.status_code == 200
        assert response.headers["Content-Type"].startswith("text/plain")
        body = response.content.decode()
        assert body.startswith("# Wodore")
        # Key links for agents: app, markdown hut documents, sitemap.
        assert "https://wodore.com/hut/{slug}" in body
        assert "/v1/huts/{slug}.md" in body
        assert "https://wodore.com/sitemap.xml" in body
        assert "OpenAPI" in body

    def test_llms_txt_uses_request_host(self, client):
        response = client.get("/llms.txt")
        assert response.status_code == 200
        body = response.content.decode()
        # Built from the request host, not hardcoded — staging serves
        # staging links.
        assert "http://testserver/v1/huts/huts" in body


class TestRobotsTxt:
    def test_non_production_denies_everything(self, client):
        response = client.get("/robots.txt")
        assert response.status_code == 200
        body = response.content.decode()
        assert "User-agent: *\nDisallow: /" in body
        assert "GPTBot" not in body

    def test_production_allows_ai_crawlers_on_public_data(self, client, monkeypatch):
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
        assert "Allow: /admin" not in body

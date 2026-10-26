"""ApiCdnCacheMiddleware — auth-state-aware CDN cache headers for /v1.

The full-stack (client) tests prove the middleware ordering against the
real corsheaders output; the RequestFactory tests pin the header matrix
(see ``server/middleware/headers.py`` docstring for the CDN context).
"""

import pytest

from django.http import HttpRequest, HttpResponse
from django.test import Client, RequestFactory

from server.middleware.headers import ApiCdnCacheMiddleware

#: Matched by the development CORS_ALLOWED_ORIGIN_REGEXES (the test
#: environment star-imports development), so corsheaders treats it as
#: an allowed origin and stamps its per-origin ACAO.
ALLOWED_ORIGIN = "https://localhost:3000"

_factory = RequestFactory()


def _process(request: HttpRequest, response: HttpResponse) -> HttpResponse:
    """Run the middleware (with a canned get_response) over ``request``."""

    def get_response(_request: HttpRequest) -> HttpResponse:
        return response

    return ApiCdnCacheMiddleware(get_response)(request)


# --------------------------------------------------------------------------
# RequestFactory matrix (middleware in isolation)
# --------------------------------------------------------------------------


def test_anonymous_get_gets_wildcard_acao_and_default_ttl() -> None:
    """Anon GET without Origin (the CDN's first fill) still carries ACAO *.

    Bunny keys its cache by URL only — whichever variant is filled first
    is served to browsers, so the wildcard must not depend on an Origin
    header being present.
    """
    response = _process(_factory.get("/v1/huts"), HttpResponse("{}"))
    assert response["Access-Control-Allow-Origin"] == "*"
    assert response["Cache-Control"] == "public, max-age=3600"


def test_corsheaders_acao_is_replaced_by_exactly_one_wildcard() -> None:
    """A per-origin ACAO corsheaders already stamped ends up as ``*``.

    ``pop`` + set guarantees a single value (ResponseHeaders stores one
    value per case-insensitive name).
    """
    response = HttpResponse("{}")
    response["access-control-allow-origin"] = ALLOWED_ORIGIN  # corsheaders casing
    response = _process(_factory.get("/v1/huts", HTTP_ORIGIN=ALLOWED_ORIGIN), response)
    assert response["Access-Control-Allow-Origin"] == "*"
    assert len(response.headers) >= 1  # headers object intact
    assert (
        sum(
            1
            for name in response.headers
            if name.lower() == "access-control-allow-origin"
        )
        == 1
    )


def test_wildcard_never_rides_with_credentials() -> None:
    """`ACAO: *` + `Access-Control-Allow-Credentials` is spec-invalid.

    Fetch forbids credentialed use of a wildcard ACAO, and the middleware
    strips any Allow-Credentials header corsheaders may have stamped, so
    anonymous /v1 reads can never authorize a credentialed cross-origin
    request — even if CORS_ALLOW_CREDENTIALS were ever enabled.
    """
    response = HttpResponse("{}")
    response["access-control-allow-origin"] = ALLOWED_ORIGIN
    response["access-control-allow-credentials"] = "true"
    response = _process(_factory.get("/v1/huts", HTTP_ORIGIN=ALLOWED_ORIGIN), response)
    assert response["Access-Control-Allow-Origin"] == "*"
    assert "Access-Control-Allow-Credentials" not in response.headers


def test_endpoint_cache_control_is_preserved_verbatim() -> None:
    """Endpoints overriding their TTL (sitemaps, SVG redirects) always win."""
    response = HttpResponse("{}")
    response["Cache-Control"] = "public, max-age=60, stale-while-revalidate=86400"
    response = _process(_factory.get("/v1/huts"), response)
    assert (
        response["Cache-Control"] == "public, max-age=60, stale-while-revalidate=86400"
    )
    assert response["Access-Control-Allow-Origin"] == "*"


def test_version_endpoint_gets_short_ttl() -> None:
    response = _process(_factory.get("/v1/version"), HttpResponse("{}"))
    assert response["Cache-Control"] == "public, max-age=300"
    assert response["Access-Control-Allow-Origin"] == "*"


def test_version_endpoint_custom_cache_control_wins() -> None:
    response = HttpResponse("{}")
    response["Cache-Control"] = "no-cache"
    response = _process(_factory.get("/v1/version"), response)
    assert response["Cache-Control"] == "no-cache"


def test_head_behaves_like_get() -> None:
    response = _process(_factory.head("/v1/huts"), HttpResponse(""))
    assert response["Access-Control-Allow-Origin"] == "*"
    assert response["Cache-Control"] == "public, max-age=3600"


def test_authenticated_get_is_never_cacheable_and_cors_untouched() -> None:
    """Bearer responses get ``private, no-store``; per-origin CORS stays."""
    response = HttpResponse("{}")
    response["access-control-allow-origin"] = ALLOWED_ORIGIN
    response = _process(
        _factory.get("/v1/huts", HTTP_AUTHORIZATION="Bearer token"), response
    )
    assert response["Cache-Control"] == "private, no-store"
    assert response["Access-Control-Allow-Origin"] == ALLOWED_ORIGIN


def test_authenticated_post_gets_no_store() -> None:
    response = _process(
        _factory.post("/v1/feedbacks", HTTP_AUTHORIZATION="Bearer token"),
        HttpResponse("{}", status=201),
    )
    assert response["Cache-Control"] == "private, no-store"


def test_authenticated_cache_control_preserved() -> None:
    response = HttpResponse("{}")
    response["Cache-Control"] = "private, max-age=0"
    response = _process(
        _factory.get("/v1/huts", HTTP_AUTHORIZATION="Bearer token"), response
    )
    assert response["Cache-Control"] == "private, max-age=0"


def test_anonymous_post_untouched() -> None:
    response = _process(_factory.post("/v1/feedbacks"), HttpResponse("{}", status=201))
    assert "Access-Control-Allow-Origin" not in response.headers
    assert "Cache-Control" not in response.headers


def test_options_untouched() -> None:
    """Preflights belong to corsheaders — no CC, no wildcard flattening."""
    response = HttpResponse("")
    response["Access-Control-Allow-Origin"] = ALLOWED_ORIGIN
    response["Access-Control-Allow-Methods"] = "GET"
    response = _process(
        _factory.options(
            "/v1/huts",
            HTTP_ORIGIN=ALLOWED_ORIGIN,
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET",
        ),
        response,
    )
    assert response["Access-Control-Allow-Origin"] == ALLOWED_ORIGIN
    assert response["Access-Control-Allow-Methods"] == "GET"
    assert "Cache-Control" not in response.headers


def test_authenticated_options_untouched() -> None:
    response = _process(
        _factory.options("/v1/huts", HTTP_AUTHORIZATION="Bearer token"),
        HttpResponse(""),
    )
    assert "Cache-Control" not in response.headers
    assert "Access-Control-Allow-Origin" not in response.headers


def test_non_api_path_untouched() -> None:
    response = _process(_factory.get("/admin/login/"), HttpResponse(""))
    assert "Access-Control-Allow-Origin" not in response.headers
    assert "Cache-Control" not in response.headers


def test_lookalike_prefix_untouched() -> None:
    """/v10/... does not start with /v1/ — the slash is part of the prefix."""
    response = _process(_factory.get("/v10/other"), HttpResponse("{}"))
    assert "Access-Control-Allow-Origin" not in response.headers
    assert "Cache-Control" not in response.headers


# --------------------------------------------------------------------------
# Full stack (client): middleware ordering vs. the real corsheaders output
# --------------------------------------------------------------------------


def test_client_anonymous_get_overrides_corsheaders_per_origin(
    client: Client,
) -> None:
    """corsheaders sets the per-origin ACAO; ours must have the final word."""
    response = client.get("/v1/version", HTTP_ORIGIN=ALLOWED_ORIGIN)
    assert response.status_code == 200
    assert response["Access-Control-Allow-Origin"] == "*"
    assert response["Cache-Control"] == "public, max-age=300"


def test_client_anonymous_get_without_origin(client: Client) -> None:
    response = client.get("/v1/version")
    assert response.status_code == 200
    assert response["Access-Control-Allow-Origin"] == "*"
    assert response["Cache-Control"] == "public, max-age=300"


def test_client_head_like_get(client: Client) -> None:
    response = client.head("/v1/version")
    assert response["Access-Control-Allow-Origin"] == "*"
    assert response["Cache-Control"] == "public, max-age=300"


def test_client_authenticated_get_no_store_and_per_origin_cors(
    client: Client,
) -> None:
    """Bearer request: no-store safety net, corsheaders' ACAO untouched."""
    response = client.get(
        "/v1/version",
        HTTP_ORIGIN=ALLOWED_ORIGIN,
        HTTP_AUTHORIZATION="Bearer test-token",
    )
    assert response.status_code == 200
    assert response["Cache-Control"] == "private, no-store"
    assert response["Access-Control-Allow-Origin"] == ALLOWED_ORIGIN


def test_client_preflight_untouched(client: Client) -> None:
    response = client.options(
        "/v1/version",
        HTTP_ORIGIN=ALLOWED_ORIGIN,
        HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET",
    )
    assert response["Access-Control-Allow-Origin"] == ALLOWED_ORIGIN
    assert "Cache-Control" not in response.headers


def test_client_anonymous_post_untouched(client: Client) -> None:
    response = client.post("/v1/version")  # 405 — headers apply regardless
    assert response.status_code == 405
    assert "Access-Control-Allow-Origin" not in response.headers
    assert "Cache-Control" not in response.headers


def test_client_non_api_path_untouched(client: Client) -> None:
    """Non-/v1 responses keep their own headers (the health view stamps
    ``max-age=0, no-cache, no-store, must-revalidate, private`` itself)."""
    response = client.get("/health/live/")
    assert response.status_code == 200
    assert "Access-Control-Allow-Origin" not in response.headers
    assert (
        response["Cache-Control"]
        == "max-age=0, no-cache, no-store, must-revalidate, private"
    )


@pytest.mark.django_db
def test_client_endpoint_cache_control_preserved_verbatim(client: Client) -> None:
    """/v1/sitemap.xml sets its own Cache-Control — never clobbered."""
    from server.apps.utils.api import SITEMAP_INDEX_TTL

    response = client.get("/v1/sitemap.xml")
    assert response.status_code == 200
    assert response["Cache-Control"] == f"public, max-age={SITEMAP_INDEX_TTL}"
    assert response["Access-Control-Allow-Origin"] == "*"

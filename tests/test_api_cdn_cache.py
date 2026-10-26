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


def test_version_ttl_is_not_a_middleware_special_case() -> None:
    """The short /v1/version TTL comes from the view now — the
    middleware stamps only the generic default (the view's header then
    wins via only-if-unset, pinned end-to-end by the client tests)."""
    response = _process(_factory.get("/v1/version"), HttpResponse("{}"))
    assert response["Cache-Control"] == "public, max-age=3600"
    assert response["Access-Control-Allow-Origin"] == "*"


def test_version_endpoint_custom_cache_control_wins() -> None:
    response = HttpResponse("{}")
    response["Cache-Control"] = "no-cache"
    response = _process(_factory.get("/v1/version"), response)
    assert response["Cache-Control"] == "no-cache"


@pytest.mark.parametrize("status", [400, 404, 429, 500])
def test_anonymous_get_error_responses_are_no_store(status: int) -> None:
    """Non-2xx responses must never seed the URL-keyed CDN cache.

    Version errors (400/410), dmr throttling (429), unknown-route 404s
    and view crashes (500) all unwind through this middleware — with a
    public TTL any one of them would become the shared CDN variant for
    the URL. ``no-store`` beats the CDN zone default (30 days), too.
    """
    response = _process(_factory.get("/v1/huts"), HttpResponse("{}", status=status))
    assert response["Cache-Control"] == "no-store"
    assert response["Access-Control-Allow-Origin"] == "*"


def test_anonymous_error_endpoint_cache_control_still_wins() -> None:
    """Only-if-unset holds on the no-store branch as well — an endpoint
    stamping its own policy on an error response keeps it."""
    response = HttpResponse("{}", status=404)
    response["Cache-Control"] = "no-cache"
    response = _process(_factory.get("/v1/huts"), response)
    assert response["Cache-Control"] == "no-cache"


def test_anonymous_redirect_is_no_store() -> None:
    """3xx redirects (e.g. APPEND_SLASH 301) get no public TTL."""
    response = _process(_factory.get("/v1/version"), HttpResponse("", status=301))
    assert response["Cache-Control"] == "no-store"
    assert response["Access-Control-Allow-Origin"] == "*"


def test_304_is_left_unstamped() -> None:
    """A 304 owns no TTL of its own (the stored 200 does) — the
    middleware stamps nothing; real 304 responses carry the endpoint's
    own Cache-Control anyway (see the client test below)."""
    response = _process(_factory.get("/v1/huts"), HttpResponse("", status=304))
    assert "Cache-Control" not in response.headers
    assert response["Access-Control-Allow-Origin"] == "*"


def test_anonymous_error_carries_exactly_one_wildcard_acao() -> None:
    """Error-body readability: 4xx still flattens to exactly one
    ``ACAO: *`` and never rides with credentials — same dance as 200s,
    outside the status guard by design."""
    response = HttpResponse("{}", status=404)
    response["access-control-allow-origin"] = ALLOWED_ORIGIN
    response["access-control-allow-credentials"] = "true"
    response = _process(_factory.get("/v1/huts", HTTP_ORIGIN=ALLOWED_ORIGIN), response)
    assert response["Access-Control-Allow-Origin"] == "*"
    assert "Access-Control-Allow-Credentials" not in response.headers
    assert (
        sum(
            1
            for name in response.headers
            if name.lower() == "access-control-allow-origin"
        )
        == 1
    )


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
# CDN-Tag (Bunny purge taxonomy — _work/261026_cdn_tags.md)
# --------------------------------------------------------------------------


def test_anonymous_2xx_get_carries_api_and_app_cdn_tags() -> None:
    """`CDN-Tag: api api:huts` — purging `api:huts` flushes one app,
    purging `api` the whole API, never untagged media/static."""
    response = _process(_factory.get("/v1/huts"), HttpResponse("{}"))
    assert response["CDN-Tag"] == "api api:huts"


@pytest.mark.parametrize(
    ("path", "tag"),
    [
        ("/v1/version", "api api:version"),
        ("/v1/openapi.json", "api api:openapi"),
        ("/v1/sitemap.xml", "api api:sitemap"),
        ("/v1/map/styles/outdoor.json", "api api:map"),
        ("/v1/huts/my-hut", "api api:huts"),
        ("/v1/availability/current/hut-slug", "api api:availability"),
    ],
)
def test_app_tag_derivation(path: str, tag: str) -> None:
    """First /v1/ path segment, extension stripped — RequestFactory
    tests, so the paths need not exist as routes."""
    response = _process(_factory.get(path), HttpResponse("{}"))
    assert response["CDN-Tag"] == tag


def test_cdn_tag_rides_with_endpoint_cache_control() -> None:
    """Views stamping their own TTL (version 300 s, sitemaps) are still
    CDN-cached — and must stay purgeable."""
    response = HttpResponse("{}")
    response["Cache-Control"] = "public, max-age=300"
    response = _process(_factory.get("/v1/version"), response)
    assert response["CDN-Tag"] == "api api:version"


@pytest.mark.parametrize("status", [301, 400, 404, 429, 500])
def test_errors_and_redirects_are_untagged(status: int) -> None:
    """no-store responses never enter the CDN cache — no purge tag."""
    response = _process(_factory.get("/v1/huts"), HttpResponse("{}", status=status))
    assert "CDN-Tag" not in response.headers


def test_304_is_untagged() -> None:
    """The stored 200 owns the tag; the revalidation carries none."""
    response = _process(_factory.get("/v1/huts"), HttpResponse("", status=304))
    assert "CDN-Tag" not in response.headers


def test_authenticated_get_is_untagged() -> None:
    response = _process(
        _factory.get("/v1/huts", HTTP_AUTHORIZATION="Bearer token"), HttpResponse("{}")
    )
    assert "CDN-Tag" not in response.headers


def test_anonymous_post_is_untagged() -> None:
    response = _process(_factory.post("/v1/feedbacks"), HttpResponse("{}", status=201))
    assert "CDN-Tag" not in response.headers


def test_non_api_path_is_untagged() -> None:
    """Media/static/admin never flow through the CDN host — and stay
    purge-immune by construction (no tag to match)."""
    response = _process(_factory.get("/media/uploads/x.jpg"), HttpResponse(""))
    assert "CDN-Tag" not in response.headers


def test_endpoint_cdn_tag_is_preserved() -> None:
    """Only-if-unset mirrors the Cache-Control rule."""
    response = HttpResponse("{}")
    response["CDN-Tag"] = "api api:custom"
    response = _process(_factory.get("/v1/huts"), response)
    assert response["CDN-Tag"] == "api api:custom"


def test_client_version_carries_cdn_tag(client: Client) -> None:
    """End-to-end: the wildcard-ACAO/TTL machinery and the tag ride
    together on a real route."""
    response = client.get("/v1/version")
    assert response.status_code == 200
    assert response["CDN-Tag"] == "api api:version"


# --------------------------------------------------------------------------
# Full stack (client): middleware ordering vs. the real corsheaders output
# --------------------------------------------------------------------------


def test_client_anonymous_get_overrides_corsheaders_per_origin(
    client: Client,
) -> None:
    """corsheaders sets the per-origin ACAO; ours must have the final word.

    The 300s TTL now comes from the view (@modify headers); the
    middleware stamps only-if-unset and lets it win.
    """
    response = client.get("/v1/version", HTTP_ORIGIN=ALLOWED_ORIGIN)
    assert response.status_code == 200
    assert response["Access-Control-Allow-Origin"] == "*"
    assert response["Cache-Control"] == "public, max-age=300"


def test_client_anonymous_get_without_origin(client: Client) -> None:
    response = client.get("/v1/version")
    assert response.status_code == 200
    assert response["Access-Control-Allow-Origin"] == "*"
    assert response["Cache-Control"] == "public, max-age=300"


def test_client_head_on_get_only_controller_is_no_store(client: Client) -> None:
    """dmr does not auto-map HEAD→GET on a get-only controller: HEAD
    /v1/version is a 405 — no-store, never a public TTL. (Pre-fix, this
    exact case stamped ``max-age=300`` on the 405 — the F1 bug.) The
    middleware-level HEAD handling is pinned by the RequestFactory test
    above."""
    response = client.head("/v1/version")
    assert response.status_code == 405
    assert response["Access-Control-Allow-Origin"] == "*"
    assert response["Cache-Control"] == "no-store"


def test_client_unknown_api_path_404_is_no_store(client: Client) -> None:
    """Django's 404 for unknown /v1/… routes must never seed the CDN."""
    response = client.get("/v1/does-not-exist")
    assert response.status_code == 404
    assert response["Cache-Control"] == "no-store"
    assert response["Access-Control-Allow-Origin"] == "*"


def test_client_trailing_slash_is_no_store(client: Client) -> None:
    """GET /v1/version/ (trailing slash) does not resolve: Django's
    APPEND_SLASH only ever adds a slash, so dmr's JSON 404 handler
    answers — no-store, never any public TTL (the version TTL lives in
    the view and the view never runs for this URL)."""
    response = client.get("/v1/version/")
    assert response.status_code == 404
    assert response["Cache-Control"] == "no-store"
    assert response["Access-Control-Allow-Origin"] == "*"


def test_client_authenticated_get_version_keeps_view_ttl(
    client: Client,
) -> None:
    """Bearer /v1/version: the view's own public TTL survives
    (only-if-unset — the same rule that protects sitemaps and ETag
    endpoints); version is user-independent, so no leak. corsheaders'
    per-origin ACAO stays untouched for authenticated requests."""
    response = client.get(
        "/v1/version",
        HTTP_ORIGIN=ALLOWED_ORIGIN,
        HTTP_AUTHORIZATION="Bearer test-token",
    )
    assert response.status_code == 200
    assert response["Cache-Control"] == "public, max-age=300"
    assert response["Access-Control-Allow-Origin"] == ALLOWED_ORIGIN


def test_client_authenticated_no_store_safety_net(client: Client) -> None:
    """Endpoints without their own Cache-Control keep the authenticated
    no-store safety net (openapi.json is anonymous-public and does not
    self-stamp)."""
    response = client.get("/v1/openapi.json", HTTP_AUTHORIZATION="Bearer t")
    assert response.status_code == 200
    assert response["Cache-Control"] == "private, no-store"


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


@pytest.mark.django_db
def test_client_304_keeps_endpoint_cache_control(client: Client) -> None:
    """End-to-end revalidation: a 304 keeps the endpoint's own TTL
    (only-if-unset) and the middleware stamps nothing on top — the
    stored 200 owns the TTL.

    Uses the meteo weather-codes endpoint (cheap ETag source, same
    seeding as tests/apps/meteo/test_api.py).
    """
    from server.apps.meteo.models import WeatherCode, WeatherCodeSymbolCollection
    from server.apps.organizations.models import Organization

    org, _ = Organization.objects.get_or_create(
        slug="test-wmo-org", defaults={"name": "Test WMO Org", "is_active": True}
    )
    WeatherCodeSymbolCollection.objects.get_or_create(
        slug="weather-icons-outlined-mono", defaults={"source_org": org}
    )
    WeatherCode.objects.get_or_create(
        code=0,
        defaults={"description_day": "Clear sky", "description_night": "Clear sky"},
    )

    url = "/v1/meteo/weather_codes"
    etag = client.get(url)["ETag"]
    response = client.get(url, HTTP_IF_NONE_MATCH=etag)
    assert response.status_code == 304
    # The endpoint's own policy, verbatim — not the middleware default,
    # not no-store.
    assert (
        response["Cache-Control"]
        == "public, max-age=3600, stale-while-revalidate=604800"
    )
    assert response["Access-Control-Allow-Origin"] == "*"

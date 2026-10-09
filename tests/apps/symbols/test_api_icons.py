"""Tests for the icons search endpoint (/v1/icons) — openspec: icon-library."""

import pytest

pytestmark = [pytest.mark.django_db]


@pytest.fixture(autouse=True)
def _imported(imported_db):
    """Both packs imported (see conftest)."""


def test_localized_ranking(client):
    """Spec: search=zelt&lang=de returns tent icons."""
    response = client.get("/v1/icons/", {"search": "zelt", "lang": "de"})
    assert response.status_code == 200
    slugs = [item["slug"] for item in response.json()]
    assert "tent" in slugs
    # Both packs carry the same slug (spec scenario).
    assert {item["pack"] for item in response.json() if item["slug"] == "tent"} == {
        "fluent-emoji",
        "noto-emoji",
    }


def test_prefix_search_autocomplete(client):
    """Autocomplete-style partial terms: prefix matches rank first."""
    response = client.get("/v1/icons/", {"search": "zel", "lang": "de"})
    assert response.status_code == 200
    slugs = [item["slug"] for item in response.json()]
    assert "tent" in slugs  # keyword 'zelt'/'zelten' startswith 'zel'
    ranked = client.get("/v1/icons/", {"search": "t", "lang": "en"}).json()
    assert {item["slug"] for item in ranked} >= {"tent"}


def test_response_schema(client):
    """Task 2.2: exactly the documented fields, asset URLs resolved."""
    response = client.get("/v1/icons/", {"search": "tent", "pack": "fluent-emoji"})
    assert response.status_code == 200
    (icon,) = [i for i in response.json() if i["slug"] == "tent"]
    assert set(icon) == {
        "slug",
        "pack",
        "unicode",
        "category",
        "subcategory",
        "lists",
        "urls",
    }
    assert icon["unicode"] == "26FA"
    assert icon["category"] == "travel-places"
    assert icon["subcategory"] == "place-other"
    assert icon["lists"] == []  # curation is manual admin data
    assert icon["urls"]["detailed"].endswith(".svg")
    assert icon["urls"]["detailed"].startswith("http://testserver/")
    assert icon["urls"]["simple"]
    assert icon["urls"]["mono"]
    # noto has one style only (design D1); unset optional fields are
    # ABSENT from the JSON (project exclude_unset convention), not null.
    noto = client.get("/v1/icons/", {"search": "tent", "pack": "noto-emoji"}).json()
    (noto_icon,) = noto
    assert noto_icon["urls"]["detailed"]
    assert noto_icon["urls"].get("simple") is None
    assert noto_icon["urls"].get("mono") is None


def test_unset_optional_fields_absent(client):
    """Unmatched icon: no keywords, category null; unicode kept (factual)."""
    response = client.get("/v1/icons/", {"search": "brand-logo"})
    (icon,) = response.json()
    assert icon["unicode"] == "E000"  # upstream metadata preserved
    assert icon["category"] is None
    assert icon["subcategory"] is None


def test_typo_tolerance(client):
    """Spec: search=montain (typo) falls back to fuzzy matching.

    The fixture equivalent: `hiknig` has no exact keyword match but is
    within edit distance 2 of `hiking`.
    """
    exact = client.get("/v1/icons/", {"search": "hiking", "lang": "en"}).json()
    assert "hiking-boot" in [item["slug"] for item in exact]
    fuzzy = client.get("/v1/icons/", {"search": "hiknig", "lang": "en"}).json()
    assert "hiking-boot" in [item["slug"] for item in fuzzy]


def test_curated_list(client):
    """Spec: list=activities returns the curated shortlist.

    The seed migration runs before test data exists, so the "activities"
    list starts empty — curation is manual (admin), the test attaches
    icons the way the admin would.
    """
    from server.apps.symbols.models import Icon, IconCuratedList, IconCuratedListEntry

    curated_list = IconCuratedList.objects.get_or_create(
        slug="activities", defaults={"name": "Activities"}
    )[0]
    for slug in ("tent", "hiking-boot"):
        IconCuratedListEntry.objects.create(
            curated_list=curated_list,
            icon=Icon.objects.get(pack__slug="fluent-emoji", slug=slug),
        )

    response = client.get("/v1/icons/", {"list": "activities", "lang": "en"})
    assert response.status_code == 200
    items = response.json()
    slugs = [item["slug"] for item in items]
    assert slugs == ["hiking-boot", "tent"]  # stable ordering: (order, slug)
    assert all(item["lists"] == ["activities"] for item in items)
    # Search inside a curated list combines both facets.
    searched = client.get(
        "/v1/icons/", {"list": "activities", "search": "zelt", "lang": "de"}
    ).json()
    assert [item["slug"] for item in searched] == ["tent"]
    # Unknown list slug → empty result (not an error).
    empty = client.get("/v1/icons/", {"list": "nope"}).json()
    assert empty == []


def test_pack_filter(client):
    """Spec: pack=noto-emoji returns only that pack."""
    response = client.get("/v1/icons/", {"pack": "noto-emoji"})
    assert response.status_code == 200
    assert response.json()
    assert {item["pack"] for item in response.json()} == {"noto-emoji"}


def test_slug_exact_lookup(client):
    """Frontend resolves a stored icon (pack + slug) to its asset URLs."""
    response = client.get(
        "/v1/icons/", {"pack": "fluent-emoji", "slug": "tent", "lang": "en"}
    )
    assert response.status_code == 200
    (icon,) = response.json()
    assert icon["slug"] == "tent"
    assert icon["urls"]["detailed"]
    # Without pack: every pack carrying the slug.
    across = client.get("/v1/icons/", {"slug": "tent"}).json()
    assert {item["pack"] for item in across} == {"fluent-emoji", "noto-emoji"}
    # Unknown slug -> empty result, not an error.
    assert client.get("/v1/icons/", {"slug": "nope"}).json() == []


def test_category_facet_and_pagination(client):
    """Spec: category facet paginates."""
    response = client.get("/v1/icons/", {"category": "place-other"})
    assert response.status_code == 200
    all_items = response.json()
    assert {item["slug"] for item in all_items} == {"tent"}
    assert len(all_items) == 2  # fluent + noto
    page = client.get(
        "/v1/icons/", {"category": "place-other", "limit": 1, "offset": 1}
    ).json()
    assert len(page) == 1
    # Group slug matches all its subgroups.
    group_page = client.get("/v1/icons/", {"category": "travel-places"}).json()
    assert {item["subcategory"] for item in group_page} == {"place-other"}


def test_locale_fallback_to_english(client):
    """Sparse de keywords degrade to en (hiking boot has no de `hiking`)."""
    response = client.get("/v1/icons/", {"search": "hiking", "lang": "de"})
    assert response.status_code == 200
    assert "hiking-boot" in [item["slug"] for item in response.json()]


def test_unknown_lang_rejected(client):
    response = client.get("/v1/icons/", {"lang": "xx"})
    assert response.status_code == 400


def test_empty_search_lists_active_icons(client):
    response = client.get("/v1/icons/", {"limit": 100})
    assert response.status_code == 200
    slugs = [item["slug"] for item in response.json()]
    assert "brand-logo" in slugs  # unmatched upstream icons remain findable
    assert "emoji-0023" in slugs


class TestCaching:
    def test_cache_headers_and_304(self, client):
        response = client.get("/v1/icons/", {"search": "tent"})
        assert response.status_code == 200
        assert response["Cache-Control"] == "public, max-age=3600"
        etag = response["ETag"]
        assert etag.startswith('"')
        assert response["Last-Modified"]

        cached = client.get("/v1/icons/", {"search": "tent"}, HTTP_IF_NONE_MATCH=etag)
        assert cached.status_code == 304
        assert cached["ETag"] == etag

    def test_etag_varies_by_query(self, client):
        first = client.get("/v1/icons/", {"search": "tent"})["ETag"]
        second = client.get("/v1/icons/", {"search": "tent", "lang": "de"})["ETag"]
        third = client.get("/v1/icons/")["ETag"]
        assert first != second
        assert first != third

    def test_etag_tracks_content_changes(self, monkeypatch, imported_db):
        """Registry modifications invalidate the ETag.

        The wiring (per-table ``modified`` maxima in the hash) is tested
        directly: the project's ``modified`` trigger stamps Postgres
        ``NOW()``, frozen within a transaction, so a real end-to-end
        invalidation needs a separate transaction (and would truncate
        the shared test database — see TransactionTestCase pitfalls).
        In production each write runs in its own transaction.
        """
        import datetime

        from django.test import RequestFactory

        from server.apps.symbols.api_icons import IconsQuery, _etag
        from server.apps.symbols.models import Icon

        request = RequestFactory().get("/v1/icons/")
        query = IconsQuery(lang="en")
        first = _etag(request, query)

        later = datetime.datetime(2030, 1, 1, tzinfo=datetime.timezone.utc)
        real_aggregate = Icon.objects.aggregate

        def bumped_aggregate(*args, **kwargs):
            result = real_aggregate(*args, **kwargs)
            if "m" in result:
                result = {**result, "m": later}
            return result

        monkeypatch.setattr(Icon.objects, "aggregate", bumped_aggregate)
        second = _etag(request, query)
        assert second != first

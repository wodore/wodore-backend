"""Tests for the category symbol SVG redirect endpoints.

Regression: the 302 responses were not declared in ``@modify``
(``extra_responses``), so dmr's response validation (enabled in
dev/test/staging) rejected the redirect with a ``validation_error``
body instead of redirecting to the SVG.
"""

from __future__ import annotations

import pytest

from django.core.files.base import ContentFile
from django.test import Client

from server.apps.categories.models import Category
from server.apps.licenses.models import License
from server.apps.symbols.models import Symbol

SVG_BODY = b'<svg xmlns="http://www.w3.org/2000/svg"/>'


def _make_symbol(slug: str, style: str = Symbol.StyleChoices.color) -> Symbol:
    """Create an active symbol with a stored SVG file."""
    license = License.objects.create(slug=f"license-{slug}")
    symbol = Symbol(slug=slug, style=Symbol.StyleChoices.color, license=license)
    symbol.svg_file.save(f"{slug}.svg", ContentFile(SVG_BODY), save=True)
    return symbol


@pytest.mark.django_db
class TestCategorySymbolSvg:
    """GET /v1/categories/symbol/{variant}/{slug}.svg"""

    def test_redirects_to_svg(self):
        symbol = _make_symbol("test-hut")
        Category.objects.create(slug="test-accommodation", symbol_color=symbol)

        response = Client().get("/v1/categories/symbol/color/test-accommodation.svg")

        assert response.status_code == 302
        assert response["Location"] == symbol.svg_file.url
        assert (
            response["Cache-Control"]
            == "public, max-age=86400, stale-while-revalidate=604800"
        )

    def test_redirects_to_svg_with_parent(self):
        symbol = _make_symbol("test-hut")
        root = Category.objects.create(slug="test-accommodation")
        child = Category.objects.create(
            slug="test-hut", parent=root, symbol_color=symbol
        )

        response = Client().get(
            "/v1/categories/symbol/color/test-accommodation/test-hut.svg"
        )

        assert response.status_code == 302
        assert response["Location"] == child.symbol_color.svg_file.url

    def test_unknown_category_returns_404(self):
        response = Client().get("/v1/categories/symbol/color/test-nope.svg")

        assert response.status_code == 404

    def test_category_without_symbol_returns_404(self):
        Category.objects.create(slug="test-accommodation")

        response = Client().get("/v1/categories/symbol/color/test-accommodation.svg")

        assert response.status_code == 404

    def test_unknown_variant_returns_400(self):
        Category.objects.create(slug="test-accommodation")

        response = Client().get("/v1/categories/symbol/bogus/test-accommodation.svg")

        assert response.status_code == 400


@pytest.mark.django_db
class TestCategoryIconUrls:
    """Category JSON returns stable SVG redirect URLs, not media links."""

    @staticmethod
    def _fixtures() -> tuple[Category, Category]:
        color = _make_symbol("test-hut")
        root = Category.objects.create(
            slug="test-accommodation",
            symbol_primitive=_make_symbol(
                "test-accommodation-p", Symbol.StyleChoices.primitive
            ),
        )
        child = Category.objects.create(
            slug="test-hut",
            parent=root,
            symbol_color=color,
            symbol_mono=_make_symbol("test-hut-m", Symbol.StyleChoices.mono),
        )
        return root, child

    def test_child_uses_parent_route_form(self):
        self._fixtures()

        response = Client().get(
            "/v1/categories/list/test-accommodation?media_mode=relative"
        )

        assert response.status_code == 200
        items = response.json()
        assert items[0]["symbol_color"] == (
            "/v1/categories/symbol/color/test-accommodation/test-hut.svg"
        )
        assert items[0]["symbol_mono"] == (
            "/v1/categories/symbol/mono/test-accommodation/test-hut.svg"
        )
        # No primitive symbol on the child: absent value
        assert items[0]["symbol_primitive"] is None

    @staticmethod
    def _root_node(response) -> dict:
        assert response.status_code == 200
        return next(
            item for item in response.json() if item["slug"] == "test-accommodation"
        )

    def test_root_uses_simple_route_form(self):
        self._fixtures()

        # list/root never includes roots themselves; the tree does.
        # level=1 keeps the payload small: the root node (with its icon
        # URLs) plus children collapsed to booleans.
        response = Client().get("/v1/categories/tree/root?media_mode=relative&level=1")

        root = self._root_node(response)
        assert root["symbol_primitive"] == (
            "/v1/categories/symbol/primitive/test-accommodation.svg"
        )

    def test_absolute_is_default(self):
        self._fixtures()

        response = Client().get("/v1/categories/tree/root?level=1")

        root = self._root_node(response)
        assert root["symbol_primitive"].startswith(
            "http://testserver/v1/categories/symbol/primitive/test-accommodation.svg"
        )

    def test_no_mode_excludes_symbol_fields(self):
        self._fixtures()

        response = Client().get("/v1/categories/tree/root?media_mode=no&level=1")

        root = self._root_node(response)
        assert "symbol_primitive" not in root

    def test_redirect_urls_resolve(self):
        """The URLs the JSON returns actually 302 to the SVG."""
        _, child = self._fixtures()
        client = Client()

        response = client.get(
            "/v1/categories/symbol/color/test-accommodation/test-hut.svg"
        )

        assert response.status_code == 302
        assert response["Location"] == child.symbol_color.svg_file.url

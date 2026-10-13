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


def _make_symbol(slug: str) -> Symbol:
    """Create an active color symbol with a stored SVG file."""
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
        assert response["Cache-Control"] == "public, max-age=604800"

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

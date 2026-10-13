"""Tests for the symbol SVG redirect endpoint.

The 302 must stay declared in ``@modify`` (dmr response validation
rejects undeclared status codes) and carries the shared
``REDIRECT_CACHE_CONTROL`` policy.
"""

from __future__ import annotations

import pytest

from django.core.files.base import ContentFile
from django.test import Client

from server.apps.api.controller import REDIRECT_CACHE_CONTROL
from server.apps.licenses.models import License
from server.apps.symbols.models import Symbol

SVG_BODY = b'<svg xmlns="http://www.w3.org/2000/svg"/>'


def _make_symbol(slug: str, style: str) -> Symbol:
    """Create an active symbol with a stored SVG file."""
    license = License.objects.create(slug=f"license-{slug}")
    symbol = Symbol(slug=slug, style=style, license=license)
    symbol.svg_file.save(f"{slug}.svg", ContentFile(SVG_BODY), save=True)
    return symbol


@pytest.mark.django_db
class TestSymbolSvg:
    """GET /v1/symbols/{style}/{slug}.svg"""

    def test_redirects_to_svg(self):
        symbol = _make_symbol("test-mountain", Symbol.StyleChoices.color)

        response = Client().get("/v1/symbols/color/test-mountain.svg")

        assert response.status_code == 302
        assert response["Location"] == symbol.svg_file.url
        assert response["Cache-Control"] == REDIRECT_CACHE_CONTROL

    def test_unknown_slug_returns_404(self):
        response = Client().get("/v1/symbols/color/test-nope.svg")

        assert response.status_code == 404

    def test_wrong_style_returns_404(self):
        _make_symbol("test-mountain", Symbol.StyleChoices.color)

        response = Client().get("/v1/symbols/mono/test-mountain.svg")

        assert response.status_code == 404

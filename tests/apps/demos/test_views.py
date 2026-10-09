"""Tests for the dev-only demos app (mapcompare view)."""

from django.http import HttpResponse
from django.test import Client, RequestFactory, override_settings

from server.apps.demos.views import mapcompare


def test_mapcompare_404_in_test(client: Client) -> None:
    """URL is not included and the view 404s when DEBUG is off."""
    response = client.get("/demos/mapcompare/")
    assert response.status_code == 404


@override_settings(DEBUG=True)
def test_mapcompare_view_renders_with_debug(rf: RequestFactory) -> None:
    """Calling the view directly with DEBUG=True renders the template."""
    request = rf.get("/demos/mapcompare/")
    response = mapcompare(request)
    assert isinstance(response, HttpResponse)
    assert response.status_code == 200
    assert b"maplibre-gl.js" in response.content
    assert b"demos/mapcompare" in response.content

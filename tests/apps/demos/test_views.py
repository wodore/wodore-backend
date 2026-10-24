"""Tests for the demos app (mapcompare view)."""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse
from django.test import RequestFactory, override_settings

from server.apps.demos.views import mapcompare


@override_settings(DEBUG=True)
def test_mapcompare_view_renders_with_debug(rf: RequestFactory) -> None:
    """Calling the view directly with DEBUG=True renders the template."""
    request = rf.get("/demos/mapcompare/")
    response = mapcompare(request)
    assert isinstance(response, HttpResponse)
    assert response.status_code == 200
    assert b"maplibre-gl.js" in response.content
    assert b"tileserver-input" in response.content
    assert b"inspect-popup" in response.content


def test_mapcompare_redirects_anonymous_in_staging(rf: RequestFactory) -> None:
    """Non-DEBUG (staging): anonymous users get redirected to admin login."""
    request = rf.get("/demos/mapcompare/")
    request.user = AnonymousUser()
    response = mapcompare(request)
    assert response.status_code == 302
    assert "login" in response.url.lower()


def test_mapcompare_rejects_non_superuser_in_staging(
    rf: RequestFactory, db: None
) -> None:
    """Non-DEBUG (staging): authenticated non-superusers also redirected."""
    User = get_user_model()
    user = User.objects.create_user(email="staff@test", password="x")  # type: ignore  # custom manager/queryset inference gap
    request = rf.get("/demos/mapcompare/")
    request.user = user
    response = mapcompare(request)
    assert response.status_code == 302


def test_mapcompare_allows_superuser_in_staging(rf: RequestFactory, db: None) -> None:
    """Non-DEBUG (staging): superusers get the page."""
    UserModel = get_user_model()
    admin = UserModel.objects.create_superuser(email="root@test", password="x")  # type: ignore  # custom manager/queryset inference gap
    request = rf.get("/demos/mapcompare/")
    request.user = admin
    response = mapcompare(request)
    assert response.status_code == 200
    assert b"maplibre-gl.js" in response.content

"""Tests for the shared LLM admin actions (LLMAdminMixin)."""

import pytest

from tests.apps.translations.conftest import FakeTranslationClient
from tests.factories.geometries import GeoPlaceFactory
from tests.factories.huts import HutFactory

from django.contrib import admin as django_admin
from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory, override_settings

from server.apps.geometries.models import GeoPlace
from server.apps.huts.models import Hut
from server.apps.translations.admin_helpers import LLMAdminMixin

pytestmark = pytest.mark.django_db

ADMIN_HELPERS = "server.apps.translations.admin_helpers"

EMPTY_API_SETTINGS = dict(
    TRANSLATION_API_BASE_URL="",
    TRANSLATION_API_KEY="",
    TRANSLATION_MODEL="",
)


def patch_admin_client(monkeypatch, fake):
    monkeypatch.setattr(f"{ADMIN_HELPERS}.TranslationClient", lambda: fake)


def make_request(method: str = "post", user=None):
    request = getattr(RequestFactory(), method)("/")
    request.user = user
    request.session = "session"
    request._messages = FallbackStorage(request)
    return request


def messages_text(request) -> list[str]:
    return [str(m) for m in get_messages(request)]


@pytest.fixture
def superuser(db):
    return User.objects.create_superuser(username="admin-lane", password="x")


@pytest.fixture
def staff_user(db):
    return User.objects.create_user(username="editor-lane", is_staff=True)


@pytest.fixture
def hut_admin():
    return django_admin.site._registry[Hut]


@pytest.fixture
def geoplace_admin():
    return django_admin.site._registry[GeoPlace]


def _hut(**kwargs) -> Hut:
    """DB-loaded hut (from_db sets _orig_* attrs Hut.save() needs)."""
    hut = HutFactory(**kwargs)
    return Hut.objects.get(pk=hut.pk)


def test_translate_action_fills_missing(monkeypatch, hut_admin, superuser):
    hut = _hut(name="Adminhütte", description="Schöne Hütte.")
    fake = FakeTranslationClient()
    patch_admin_client(monkeypatch, fake)
    request = make_request(user=superuser)

    hut_admin.translate_selected(request, Hut.objects.filter(pk=hut.pk))

    hut.refresh_from_db()
    assert hut.i18n["name_fr"] == "Adminhütte-fr"
    assert any("translated" in m for m in messages_text(request))


def test_translate_action_unconfigured(hut_admin, superuser):
    hut = _hut(name="Ohne API")
    request = make_request(user=superuser)

    with override_settings(**EMPTY_API_SETTINGS):
        hut_admin.translate_selected(request, Hut.objects.filter(pk=hut.pk))

    hut.refresh_from_db()
    assert not hut.i18n
    texts = messages_text(request)
    assert any("Translation API" in m for m in texts)
    assert not any("translated" in m for m in texts)


def test_assess_action_scores_and_reworks(monkeypatch, hut_admin, superuser):
    hut = _hut(name="Redaktionshütte", description="Kurzer Text.")
    Hut.objects.filter(pk=hut.pk).update(review_status="done")
    fake = FakeTranslationClient(assess_result={"score": 4, "summary": "Too thin."})
    patch_admin_client(monkeypatch, fake)
    request = make_request(user=superuser)

    hut_admin.assess_selected(request, Hut.objects.filter(pk=hut.pk))

    hut.refresh_from_db()
    assert hut.description_quality == 4
    assert hut.review_status == "rework"
    assert any("4/10" in m for m in messages_text(request))


def test_assess_action_reports_skips(monkeypatch, hut_admin, superuser):
    hut = _hut(name="Leerhütte", description="")
    fake = FakeTranslationClient()
    patch_admin_client(monkeypatch, fake)
    request = make_request(user=superuser)

    hut_admin.assess_selected(request, Hut.objects.filter(pk=hut.pk))

    assert any("empty" in m for m in messages_text(request))
    assert fake.calls == []  # no API call for empty descriptions


def test_assess_action_on_geoplace(monkeypatch, geoplace_admin, superuser):
    place = GeoPlaceFactory(name="Admin Ort", description="Ein beschriebener Ort.")
    GeoPlace.objects.filter(pk=place.pk).update(review_status="done")
    fake = FakeTranslationClient(assess_result={"score": 3, "summary": "Bad."})
    patch_admin_client(monkeypatch, fake)
    request = make_request(user=superuser)

    geoplace_admin.assess_selected(request, GeoPlace.objects.filter(pk=place.pk))

    place.refresh_from_db()
    assert place.description_quality == 3
    assert place.review_status == "rework"


def test_button_view_post_redirects(monkeypatch, hut_admin, superuser):
    hut = _hut(name="Buttonhütte", description="Text.")
    fake = FakeTranslationClient()
    patch_admin_client(monkeypatch, fake)
    request = make_request(user=superuser)

    response = hut_admin.llm_translate_view(request, hut.pk)

    assert response.status_code == 302
    assert f"/{hut.pk}/change/" in response.url
    hut.refresh_from_db()
    assert hut.i18n["name_fr"] == "Buttonhütte-fr"


def test_button_view_get_not_allowed(hut_admin, superuser):
    request = make_request(method="get", user=superuser)
    response = hut_admin.llm_translate_view(request, 1)
    assert response.status_code == 405


def test_button_view_requires_change_permission(hut_admin, staff_user):
    request = make_request(user=staff_user)
    with pytest.raises(PermissionDenied):
        hut_admin.llm_assess_view(request, 1)


def test_mixin_registered_on_both_admins(hut_admin, geoplace_admin):
    assert isinstance(hut_admin, LLMAdminMixin)
    assert isinstance(geoplace_admin, LLMAdminMixin)
    assert "description_quality_display" in hut_admin.list_display
    assert "description_quality_display" in geoplace_admin.list_display

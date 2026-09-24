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


def test_changelist_actions_registered_with_change_permission(
    hut_admin, geoplace_admin
):
    """Both bulk actions must actually appear in the changelist dropdown."""
    for model_admin in (hut_admin, geoplace_admin):
        assert "translate_selected" in model_admin.actions
        assert "assess_selected" in model_admin.actions
    # View-only staff must not be able to run them (Django filters
    # changelist actions by allowed_permissions). The unfold @action
    # decorator's return typing hides the attribute (runtime-set).
    assert (
        LLMAdminMixin.translate_selected.allowed_permissions  # pyright: ignore[reportAttributeAccessIssue]  # runtime-set by @action
        == ["change"]
    )
    assert (
        LLMAdminMixin.assess_selected.allowed_permissions  # pyright: ignore[reportAttributeAccessIssue]  # runtime-set by @action
        == ["change"]
    )


# --- Feature gating: UI only when the translation API is configured ------

ENABLED_API_SETTINGS = dict(
    TRANSLATION_API_BASE_URL="https://api.example/v1",
    TRANSLATION_API_KEY="test-key",
    TRANSLATION_MODEL="test-model",
)


def _runner_registry():
    from django_admin_runner import registry

    return registry._registry


def test_actions_hidden_when_api_unconfigured(hut_admin, superuser):
    with override_settings(**EMPTY_API_SETTINGS):
        actions = hut_admin.get_actions(make_request(user=superuser))
    assert "translate_selected" not in actions
    assert "assess_selected" not in actions


def test_actions_listed_when_api_configured(hut_admin, superuser):
    with override_settings(**ENABLED_API_SETTINGS):
        actions = hut_admin.get_actions(make_request(user=superuser))
    assert "translate_selected" in actions
    assert "assess_selected" in actions


def test_llm_button_urls_absent_when_unconfigured(hut_admin):
    with override_settings(**EMPTY_API_SETTINGS):
        names = [p.name for p in hut_admin.get_urls() if p.name]
    assert not any("llm" in name for name in names)


def test_llm_button_urls_present_when_configured(hut_admin):
    with override_settings(**ENABLED_API_SETTINGS):
        names = [p.name for p in hut_admin.get_urls()]
    assert any("llm_translate" in name for name in names)
    assert any("llm_assess" in name for name in names)


def _captured_change_form_context(monkeypatch, model_admin, obj):
    """Run render_change_form with the real chain but a stub base render.

    Full-page admin renders require the debug-toolbar context, which the
    plain test client does not provide — so capture the context instead.
    """
    from django.contrib import admin as django_model_admin

    captured: dict = {}

    def fake_render(self, request, context, **kwargs):
        captured.update(context)
        return "ok"

    monkeypatch.setattr(
        django_model_admin.ModelAdmin, "render_change_form", fake_render
    )
    model_admin.render_change_form(make_request(), {"original": obj})
    return captured


def test_change_form_buttons_hidden_when_unconfigured(monkeypatch, hut_admin):
    hut = _hut(name="Gatedhütte A")
    with override_settings(**EMPTY_API_SETTINGS):
        context = _captured_change_form_context(monkeypatch, hut_admin, hut)
    assert "llm_translate_url" not in context
    assert "llm_assess_url" not in context


def test_change_form_buttons_shown_when_configured(monkeypatch, hut_admin):
    hut = _hut(name="Gatedhütte B")
    # URL registration is covered by the get_urls() tests above; here we
    # assert the gating branch sets the context (reverse stubbed — the
    # root urlconf materializes admin URLs at import, so live reverse
    # can't react to override_settings).
    monkeypatch.setattr(f"{ADMIN_HELPERS}.reverse", lambda *a, **k: "/stub")
    with override_settings(**ENABLED_API_SETTINGS):
        context = _captured_change_form_context(monkeypatch, hut_admin, hut)
    assert context.get("llm_translate_url") == "/stub"
    assert context.get("llm_assess_url") == "/stub"


def test_runner_registration_absent_when_unconfigured():
    # Default import-time state: vars unset -> commands never registered.
    assert "update_translations" not in _runner_registry()
    assert "assess_descriptions" not in _runner_registry()


def test_runner_registration_present_when_configured():
    import importlib

    import server.apps.translations.management.commands.update_translations as mod

    try:
        with override_settings(**ENABLED_API_SETTINGS):
            importlib.reload(mod)
        assert "update_translations" in _runner_registry()
    finally:
        # No unregister API in the package: restore manually.
        _runner_registry().pop("update_translations", None)


def test_runner_registration_assess_command_when_configured():
    import importlib

    import server.apps.translations.management.commands.assess_descriptions as mod

    try:
        with override_settings(**ENABLED_API_SETTINGS):
            importlib.reload(mod)
        assert "assess_descriptions" in _runner_registry()
    finally:
        _runner_registry().pop("assess_descriptions", None)

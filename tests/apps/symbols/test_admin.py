"""Admin changelist render tests (openspec: icon-library).

Regression: Unfold's ``@display(header=True)`` requires display
methods to return a list/tuple — a plain string crashes the
changelist with ``UnfoldException: Display header requires list or
tuple``. These tests render every icon-library changelist for real
(debug toolbar stripped: it raises an unrelated
``SuspiciousFileOperation`` in in-process requests).
"""

import pytest

from django.contrib import admin as django_admin
from django.contrib.auth import get_user_model
from django.test import Client

pytestmark = [pytest.mark.django_db]


@pytest.fixture
def admin_client(settings, imported_db, db):
    """Superuser client rendering admin pages without the debug toolbar."""
    settings.MIDDLEWARE = [m for m in settings.MIDDLEWARE if "debug_toolbar" not in m]
    settings.ALLOWED_HOSTS = list(settings.ALLOWED_HOSTS) + ["testserver"]
    admin = get_user_model().objects.create_superuser(  # pyright: ignore[reportAttributeAccessIssue]  # custom UserManager: django-stubs gap
        email="admin@example.com", password="pw"
    )
    client = Client()
    client.force_login(admin)
    return client


@pytest.mark.parametrize(
    "url",
    [
        "/admin/symbols/icon/",
        "/admin/symbols/iconcuratedlist/",
        "/admin/symbols/symbolcollection/",
        "/admin/categories/category/",
    ],
)
def test_changelist_renders(admin_client, url):
    """All icon-library changelists render (incl. header displays)."""
    response = admin_client.get(url)
    assert response.status_code == 200, getattr(response, "content", b"")[:300]


def test_header_displays_return_tuples(emoji_fixture):
    """Unit pin: header=True displays must return list/tuple always."""

    from django.core.management import call_command

    from server.apps.symbols.admin import (
        IconAdmin,
        IconCuratedListAdmin,
        SymbolCollectionAdmin,
    )
    from server.apps.symbols.models import Icon, IconCuratedList, SymbolCollection

    call_command(
        "icon_import",
        "--source",
        "fluent",
        "--ref",
        "test-ref",
        "--locales",
        "de,en",
        "--data-dir",
        str(emoji_fixture),
    )
    icon_admin = IconAdmin(Icon, django_admin.site)
    matched = Icon.objects.get(pack__slug="fluent-emoji", slug="tent")
    unmatched = Icon.objects.get(pack__slug="fluent-emoji", slug="brand-logo")

    assert isinstance(icon_admin.name_i18n_display(matched), tuple)
    assert isinstance(icon_admin.category_display(matched), tuple)
    assert isinstance(icon_admin.category_display(unmatched), tuple)

    pack_admin = SymbolCollectionAdmin(SymbolCollection, django_admin.site)
    pack = SymbolCollection.objects.get(slug="fluent-emoji")
    assert isinstance(pack_admin.source_org_display(pack), tuple)

    list_admin = IconCuratedListAdmin(IconCuratedList, django_admin.site)
    curated_list = IconCuratedList.objects.create(slug="x", name="X")
    assert isinstance(list_admin.name_i18n_display(curated_list), tuple)

"""Admin consumption of visit counters (spec: place-visit-counter).

Covers: the window annotations behind the sortable visits columns
(30-day and one-year windows, content-type isolation, zero fallback)
and the Hut / GeoPlace changelists actually sorting by them.
"""

from datetime import timedelta

import pytest

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from django.utils import timezone as djtz

from server.apps.visits.models import ObjectVisitDay, visit_window_annotation

pytestmark = pytest.mark.django_db


def _count(obj, days_ago: int, n: int) -> None:
    ObjectVisitDay.objects.create(
        content_type=ContentType.objects.get_for_model(obj),
        object_id=obj.pk,
        day=djtz.now().date() - timedelta(days=days_ago),
        count=n,
    )


@pytest.fixture
def superuser(db):
    user = get_user_model().objects.create_superuser(  # pyright: ignore[reportAttributeAccessIssue]  # custom manager
        email="visits-admin@example.com", password="pw"
    )
    return user


@pytest.fixture
def hut(seed_data):
    from server.apps.huts.models import Hut

    return Hut.objects.filter(is_active=True, is_public=True).first()


@pytest.fixture
def place(seed_data):
    from server.apps.geometries.models import GeoPlace

    return GeoPlace.objects.filter(is_active=True, is_public=True).first()


class TestWindowAnnotation:
    def test_windows_and_content_type_isolation(self, hut, place):
        _count(hut, days_ago=0, n=10)  # in both windows
        _count(hut, days_ago=100, n=40)  # only in the 365d window
        _count(place, days_ago=0, n=7)  # other content type

        from server.apps.geometries.models import GeoPlace
        from server.apps.huts.models import Hut

        annotated_hut = Hut.objects.annotate(
            v30=visit_window_annotation(Hut, days=30),
            v365=visit_window_annotation(Hut, days=365),
        ).get(pk=hut.pk)
        assert annotated_hut.v30 == 10
        assert annotated_hut.v365 == 50  # 10 + 40

        # The place's own annotation counts only geoplace rows …
        place_v30 = (
            GeoPlace.objects.annotate(v30=visit_window_annotation(GeoPlace, days=30))
            .values_list("v30", flat=True)
            .get(pk=place.pk)
        )
        assert place_v30 == 7

        # … and a hut-typed annotation on a geoplace never sees hut rows.
        cross = (
            GeoPlace.objects.annotate(v30=visit_window_annotation(Hut, days=30))
            .values_list("v30", flat=True)
            .get(pk=place.pk)
        )
        assert cross == 0

    def test_no_counters_annotate_zero(self, hut):
        from server.apps.huts.models import Hut

        annotated = Hut.objects.annotate(v30=visit_window_annotation(Hut, days=30)).get(
            pk=hut.pk
        )
        assert annotated.v30 == 0  # Coalesce, not NULL


class TestChangelistSorting:
    """Sorting is asserted through Django's ChangeList (the machinery
    behind ?o=), independent of template rendering. Changelist rendering
    itself was broken under unfold 0.87 (pre-#269); it is smoke-tested
    separately in TestChangelistRendering below."""

    def _sorted_pks(self, admin_cls, model, column, user, descending=True):
        from django.contrib import admin as django_admin
        from django.test import RequestFactory

        index = list(admin_cls.list_display).index(column) + 1
        request = RequestFactory().get(
            "/", {"o": f"-{index}" if descending else str(index)}
        )
        request.user = user
        ma = admin_cls(model, django_admin.site)
        cl = ma.get_changelist_instance(request)
        return list(cl.queryset.values_list("pk", flat=True))

    def test_hut_changelist_sorts_by_visits(self, superuser, seed_data, hut):
        from server.apps.huts.admin import HutsAdmin
        from server.apps.huts.models import Hut

        popular = hut
        quiet = (
            Hut.objects.filter(is_active=True, is_public=True)
            .exclude(pk=popular.pk)
            .first()
        )
        assert quiet is not None
        _count(popular, days_ago=0, n=25)
        _count(quiet, days_ago=0, n=1)

        pks = self._sorted_pks(HutsAdmin, Hut, "visits_30d", user=superuser)
        assert pks.index(popular.pk) < pks.index(quiet.pk)  # most visits first

    def test_geoplace_changelist_sorts_by_visits(self, superuser, seed_data, place):
        from server.apps.geometries.admin import GeoPlaceAdmin
        from server.apps.geometries.models import GeoPlace

        popular = place
        quiet = (
            GeoPlace.objects.filter(is_active=True, is_public=True)
            .exclude(pk=popular.pk)
            .first()
        )
        assert quiet is not None
        _count(popular, days_ago=0, n=25)
        _count(quiet, days_ago=0, n=1)

        pks = self._sorted_pks(GeoPlaceAdmin, GeoPlace, "visits_30d", user=superuser)
        assert pks.index(popular.pk) < pks.index(quiet.pk)

    def test_columns_are_sortable(self):
        """Both columns expose admin_order_field (Django sorting contract)."""
        from server.apps.geometries.admin import GeoPlaceAdmin
        from server.apps.huts.admin import HutsAdmin

        for admin_cls in (HutsAdmin, GeoPlaceAdmin):
            for column in ("visits_30d", "visits_365d"):
                assert getattr(admin_cls, column).admin_order_field == column


class TestChangelistRendering:
    """Render smoke tests — possible since the unfold 0.108 upgrade (#269);
    under unfold 0.87 every changelist render raised TypeError."""

    @pytest.mark.parametrize(
        ("url_name", "admin_cls", "model"),
        [
            ("admin:huts_hut_changelist", "HutsAdmin", "Hut"),
            (
                "admin:geometries_geoplace_changelist",
                "GeoPlaceAdmin",
                "GeoPlace",
            ),
        ],
    )
    def test_changelist_renders_with_visit_columns(
        self, client, superuser, seed_data, url_name, admin_cls, model
    ):
        if url_name.startswith("admin:huts"):
            from server.apps.huts import admin as admin_mod
        else:
            from server.apps.geometries import admin as admin_mod

        list_display = getattr(admin_mod, admin_cls).list_display
        client.force_login(superuser)
        response = client.get(reverse(url_name))
        assert response.status_code == 200
        content = response.content.decode()
        for column in ("visits_30d", "visits_365d"):
            index = list(list_display).index(column) + 1
            assert f"o={index}" in content  # sortable header link present

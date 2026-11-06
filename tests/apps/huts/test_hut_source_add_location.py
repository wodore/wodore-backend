"""Regression tests for ``HutSource.add()`` with coordinate-less locations.

A stored ``HutSource.location`` can be ``None`` (Prenota rows whose
structure page failed yield no coordinates — ``add_hut_source_db`` keeps
them for manual completion), and an incoming source can equally lack a
location. The location-diff check called ``.distance()`` on the stored
location unconditionally, so any ``None`` on either side raised
``AttributeError: 'NoneType' object has no attribute 'distance'`` and
aborted the whole ``hut_sources`` import run (Sentry BACKEND-DJANGO-S:
stored coordinate-less row + re-fetch that now returned coordinates).
"""

from typing import Any

import pytest

from tests.factories import OrganizationFactory

from django.contrib.gis.geos import Point

from server.apps.huts.models import HutSource
from server.apps.organizations.models import Organization
from server.core import UpdateCreateStatus

pytestmark = pytest.mark.django_db

SRC_DATA: dict[str, Any] = {
    "name": "Masseria Rossella",
    "detail": {"photo_urls": []},
}


@pytest.fixture
def org() -> Organization:
    return OrganizationFactory(slug="prenota-rifugi")


def _stored(org: Organization, location: Point | None) -> HutSource:
    """Current DB row for source '42' — version 0, reviewed as done."""
    return HutSource.objects.create(
        source_id="42",
        organization=org,
        name="Masseria Rossella",
        location=location,
        source_data=SRC_DATA,
        review_status=HutSource.ReviewStatusChoices.done,
    )


def _incoming(org: Organization, location: Point | None) -> HutSource:
    """Unsaved re-fetch of the same source (identical source_data)."""
    return HutSource(
        source_id="42",
        organization=org,
        name="Masseria Rossella",
        location=location,
        source_data=SRC_DATA,
    )


def _assert_review_version(
    result: HutSource, stored: HutSource, expected_loc_diff: str
) -> None:
    """The diff path: new version row in review, old row retired."""
    assert result.pk is not None and result.pk != stored.pk
    assert result.version == stored.version + 1
    assert result.is_current is True
    assert result.review_status == HutSource.ReviewStatusChoices.review
    assert result.review_comment == expected_loc_diff
    assert result.previous_object_id == stored.pk  # pyright: ignore[reportAttributeAccessIssue]
    stored.refresh_from_db()
    assert stored.is_current is False
    assert stored.review_status == HutSource.ReviewStatusChoices.old


class TestAddLocationDiff:
    def test_none_to_none_is_no_change(self, org: Organization) -> None:
        """Both sides coordinate-less: no location diff, no new version."""
        stored = _stored(org, None)
        result, status = HutSource.add(_incoming(org, None))

        assert status is UpdateCreateStatus.no_change
        assert result.pk == stored.pk
        assert HutSource.objects.count() == 1

    def test_none_to_point_creates_review_version(self, org: Organization) -> None:
        """Stored None + incoming Point (today's staging crash): new version."""
        stored = _stored(org, None)
        result, status = HutSource.add(_incoming(org, Point(9.0, 45.0)))

        assert status is UpdateCreateStatus.updated
        _assert_review_version(
            result, stored, "Location changed from 'None' to '(9.0, 45.0)'"
        )

    def test_point_to_none_creates_review_version(self, org: Organization) -> None:
        """Stored Point + incoming None: analogous new version in review."""
        stored = _stored(org, Point(9.0, 45.0))
        result, status = HutSource.add(_incoming(org, None))

        assert status is UpdateCreateStatus.updated
        _assert_review_version(
            result, stored, "Location changed from '(9.0, 45.0)' to 'None'"
        )

    def test_point_to_moved_point_creates_review_version(
        self, org: Organization
    ) -> None:
        """Point/Point beyond the distance threshold keeps the old logic."""
        stored = _stored(org, Point(9.0, 45.0))
        result, status = HutSource.add(_incoming(org, Point(10.0, 46.0)))

        assert status is UpdateCreateStatus.updated
        _assert_review_version(
            result, stored, "Location changed from '(9.0, 45.0)' to '(10.0, 46.0)'"
        )

    def test_same_point_is_no_change(self, org: Organization) -> None:
        """Identical points are below the threshold: no new version."""
        stored = _stored(org, Point(9.0, 45.0))
        result, status = HutSource.add(_incoming(org, Point(9.0, 45.0)))

        assert status is UpdateCreateStatus.no_change
        assert result.pk == stored.pk
        assert HutSource.objects.count() == 1

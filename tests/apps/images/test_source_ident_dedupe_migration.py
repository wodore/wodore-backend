"""Images migrations 0033/0034 + runtime tolerance — two Sentry regressions.

Legacy bug (155850205): ``source_ident`` had no unique constraint, so
concurrent syncs (request write-through vs. django-q2 refresh vs.
``geoimages_pin`` sweeps) could mint twin ``Image`` rows — every later
sync then crashed with ``MultipleObjectsReturned`` ("get() returned more
than one Image -- it returned 2!", hut cedullo). Migration 0033 merges
the twins; migration 0034 adds the partial unique constraint. The pin
runtime resolves the canonical (oldest) row either way.

Deploy bug (BACKEND-DJANGO-8): 0033 as shipped also added the constraint
— DML + ``CREATE UNIQUE INDEX`` in one atomic migration (one
transaction). Postgres refuses index builds while the transaction has
pending deferred trigger events (Django FKs are ``DEFERRABLE INITIALLY
DEFERRED``), so the staging migrate job died with ``cannot CREATE INDEX
"images_image" because it has pending trigger events``. The constraint
now lives in its own migration; ``test_source_ident_migration_atomicity``
pins that arrangement by driving 0033 + 0034 through the real
MigrationExecutor with twins present.

The twins are minted by dropping 0034's constraint for the whole module.
DDL must live outside the per-test transactions — Postgres refuses CREATE
INDEX while the ``TimeStampedModel`` modified-trigger has pending events
in the open transaction — and ``django_db(transaction=True)`` would flush
the session's seed data, so the drop/re-add brackets the module instead
(test DML rolls back with each atom, leaving the index a clean table).
"""

import importlib
from datetime import UTC, datetime, timedelta

import pytest
from pytest_django.plugin import DjangoDbBlocker

from server.apps.geometries.models import GeoPlace, GeoPlaceImageAssociation
from server.apps.huts.models import Hut, HutImageAssociation
from server.apps.images.models import Image, ImageTag
from server.apps.licenses.models import License

pytestmark = pytest.mark.django_db

MIGRATION = (
    "server.apps.images.migrations.0033_merge_duplicate_pins_unique_source_ident"
)
CONSTRAINT_NAME = "images_image_source_ident_unique"
IDENT = "wikicommons:File:Cedullo.jpg"


class _RealApps:
    """Migrations get a historical registry; the merge logic only calls
    ``get_model()``, so the live registry exercises the same code path."""

    def get_model(self, app_label: str, model_name: str):
        from django.apps import apps

        return apps.get_model(app_label, model_name)


def _constraint():
    return next(
        constraint
        for constraint in Image._meta.constraints
        if constraint.name == CONSTRAINT_NAME
    )


@pytest.fixture(scope="module", autouse=True)
def legacy_schema(django_db_setup: None, django_db_blocker: DjangoDbBlocker):
    """Pre-0033 schema for the whole module: no source_ident uniqueness."""
    from django.db import connection

    with django_db_blocker.unblock():
        with connection.schema_editor() as editor:
            editor.remove_constraint(Image, _constraint())
    yield
    with django_db_blocker.unblock():
        with connection.schema_editor() as editor:
            editor.add_constraint(Image, _constraint())


@pytest.fixture
def license_obj():
    return License.objects.get_or_create(
        slug="cc-by-sa-4-0", defaults={"no_publication": False}
    )[0]


@pytest.fixture
def hut():
    from tests.factories.huts import HutFactory

    # Re-fetch: _orig_slug (Hut.save's slug-change guard) is set in
    # from_db, which factory-created instances never went through.
    hut = HutFactory(slug="dedupe-hut")
    return Hut.objects.get(pk=hut.pk)


@pytest.fixture
def place():
    from tests.factories.geometries import GeoPlaceFactory

    return GeoPlaceFactory(slug="dedupe-place")


class TestMergeDuplicatePins:
    def test_merges_twins_and_repoints_associations(
        self, license_obj: License, hut: Hut, place: GeoPlace
    ):
        keeper = Image.objects.create(
            source_ident=IDENT,
            license=license_obj,
            image_meta={"provider_score": 10},
            created=datetime(2026, 1, 1, tzinfo=UTC),
        )
        twin = Image.objects.create(  # minted by a concurrent sync
            source_ident=IDENT,
            license=license_obj,
            image_meta={"provider_score": 10},
            created=datetime(2026, 1, 2, tzinfo=UTC),
        )
        # Twin-only hut link: must be re-pointed to the keeper.
        HutImageAssociation.objects.create(hut=hut, image=twin, score=42)
        # Shadowed place link: keeper already links the place — the twin's
        # link must be dropped, the keeper's own (curated score) survive.
        GeoPlaceImageAssociation.objects.create(geo_place=place, image=keeper, score=7)
        GeoPlaceImageAssociation.objects.create(geo_place=place, image=twin, score=9)
        # Only the twin carries pixels (a later localized download).
        twin.image = "images/twin.jpg"
        twin.save(update_fields=["image"])

        migration = importlib.import_module(MIGRATION)
        migration.merge_duplicate_pins(_RealApps(), None)

        assert Image.objects.filter(source_ident=IDENT).count() == 1
        keeper.refresh_from_db()
        assert keeper.image.name == "images/twin.jpg"  # pixels adopted
        hut_assoc = HutImageAssociation.objects.get(hut=hut)
        assert hut_assoc.image_id == keeper.id  # re-pointed, score preserved
        assert hut_assoc.score == 42
        place_assoc = GeoPlaceImageAssociation.objects.get(geo_place=place)
        assert place_assoc.image_id == keeper.id
        assert place_assoc.score == 7  # the keeper's link won, not the twin's

    def test_merges_triples_and_adopts_tags(self, license_obj: License, hut: Hut):
        """N > 2 twins per ident: every duplicate collapses into the oldest
        row, and tags carried only by dupes survive on the keeper (review
        N-3/N-4 coverage)."""
        keeper = Image.objects.create(
            source_ident=IDENT,
            license=license_obj,
            created=datetime(2026, 1, 1, tzinfo=UTC),
        )
        dupes = [
            Image.objects.create(
                source_ident=IDENT,
                license=license_obj,
                created=datetime(2026, 1, 2, tzinfo=UTC) + timedelta(days=n),
            )
            for n in range(2)
        ]
        keeper_tag = ImageTag.objects.create(slug="keeper-tag", name_en="Keeper")
        dupe_tag = ImageTag.objects.create(slug="dupe-tag", name_en="Dupe")
        keeper.tags.add(keeper_tag)
        dupes[0].tags.add(dupe_tag)
        # Each dupe links the hut; the keeper does not yet.
        for dupe in dupes:
            HutImageAssociation.objects.create(hut=hut, image=dupe, score=10)

        migration = importlib.import_module(MIGRATION)
        migration.merge_duplicate_pins(_RealApps(), None)

        assert Image.objects.filter(source_ident=IDENT).count() == 1
        keeper.refresh_from_db()
        # Both links re-pointed onto the single survivor (not shadowed —
        # they belonged to *different* dupe rows, so both are kept).
        assert HutImageAssociation.objects.filter(hut=hut, image=keeper).count() == 1
        # Tag union survives the merge.
        assert set(keeper.tags.values_list("slug", flat=True)) == {
            "keeper-tag",
            "dupe-tag",
        }

    def test_unique_idents_untouched(self, license_obj: License, hut: Hut):
        pin = Image.objects.create(
            source_ident=IDENT,
            license=license_obj,
            created=datetime(2026, 1, 1, tzinfo=UTC),
        )
        other = Image.objects.create(
            source_ident="wikicommons:File:Other.jpg",
            license=license_obj,
            created=datetime(2026, 1, 1, tzinfo=UTC),
        )
        HutImageAssociation.objects.create(hut=hut, image=pin, score=42)
        HutImageAssociation.objects.create(hut=hut, image=other, score=42)

        migration = importlib.import_module(MIGRATION)
        migration.merge_duplicate_pins(_RealApps(), None)

        assert Image.objects.count() == 2
        assert HutImageAssociation.objects.filter(hut=hut).count() == 2

    def test_identless_rows_never_merged(self, license_obj: License):
        """Empty idents are not a dedupe group — every identless upload
        survives (the constraint ignores them, and so must the merge)."""
        for _ in range(3):
            Image.objects.create(source_ident="", license=license_obj)

        migration = importlib.import_module(MIGRATION)
        migration.merge_duplicate_pins(_RealApps(), None)

        assert Image.objects.filter(source_ident="").count() == 3


class TestPinningWithLegacyTwins:
    """The runtime half of the regression: pin syncs over legacy twin rows
    must refresh the canonical (oldest) image instead of raising
    ``MultipleObjectsReturned`` (the exact cedullo crash)."""

    def test_sync_refreshes_canonical_row(self, hut: Hut, license_obj: License):
        from tests.apps.geometries.test_image_pinning import _result

        from server.apps.geometries.pinning import pin_place_images

        older = Image.objects.create(
            source_ident="wikicommons:File:Test.jpg",
            license=license_obj,
            image_meta={"provider_score": 10},
            created=datetime(2026, 1, 1, tzinfo=UTC),
        )
        Image.objects.create(  # the twin a concurrent sync minted
            source_ident="wikicommons:File:Test.jpg",
            license=license_obj,
            image_meta={"provider_score": 10},
            created=datetime(2026, 1, 2, tzinfo=UTC),
        )
        HutImageAssociation.objects.create(hut=hut, image=older, score=5)

        stats = pin_place_images(hut, [_result(score=80)])

        assert stats.created == 0
        assert stats.updated == 1  # canonical (oldest) row refreshed — no crash
        older.refresh_from_db()
        assert older.image_meta["provider_score"] == 80
        # The association stays a single link on the canonical row.
        assert HutImageAssociation.objects.filter(hut=hut).count() == 1
        assert HutImageAssociation.objects.get(hut=hut).image_id == older.id

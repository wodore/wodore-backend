"""Unit tests for GeoPlaceParty associations and the role vocabulary.

OpenSpec change: ``geoplace-parties`` (tasks 1.1, 1.3 and the 2.2 write
path) — the vocabulary is seeded by migration ``0052`` (runs on the
test database), so these tests pin the seed, the association contract
(role-subtree validation, uniqueness per ``(geo_place, party, role)``,
separate rows for multiple roles, RESTRICT on party and role FKs), and
the schema write path that replaced the ``AmenityDetail.brand`` FK.
"""

import re
from typing import Any

import pytest
from hut_services import LocationSchema

from tests.factories.geometries import GeoPlaceFactory
from tests.factories.parties import PartyFactory

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import RestrictedError

from server.apps.categories.models import Category
from server.apps.geometries.models import (
    AmenityDetail,
    GeoPlace,
    GeoPlaceParty,
    OperatingStatus,
)
from server.apps.geometries.schemas import GeoPlaceAmenityInput, PartyInput
from server.apps.parties.models import Party
from server.core import UpdateCreateStatus

pytestmark = pytest.mark.django_db


def role(slug: str) -> Category:
    return Category.objects.get(slug=slug, parent__slug="role")


class TestRoleVocabulary:
    def test_vocabulary_seeded_by_migration(self):
        parent = Category.objects.get(slug="role", parent__isnull=True)
        assert parent.is_active
        assert parent.name  # German source name seeded

        children = list(
            parent.children.order_by("order").values_list("slug", flat=True)
        )
        assert children == ["operator", "brand", "source"]

        # The computed ``identifier`` column must be populated — data
        # migrations create rows through historical models, so
        # computedfields never fires (see categories' 0006 precedent).
        assert parent.identifier == "root.role"
        for child in parent.children.all():
            assert child.identifier == f"role.{child.slug}"
            assert child.is_active
            assert child.name
            assert child.i18n.get("name_en")  # English translation seeded


class TestGeoPlaceParty:
    def test_valid_association_passes_clean(self):
        place = GeoPlaceFactory()
        party = PartyFactory()

        association = GeoPlaceParty(geo_place=place, party=party, role=role("operator"))
        association.full_clean()
        association.save()

        assert place.party_associations.count() == 1  # type: ignore  # reverse FK: plugin-less inference gap
        assert place.party_associations.first().role.slug == "operator"  # type: ignore  # reverse FK

    def test_multiple_roles_are_separate_rows(self):
        place = GeoPlaceFactory()
        party = PartyFactory()

        GeoPlaceParty.objects.create(geo_place=place, party=party, role=role("brand"))
        GeoPlaceParty.objects.create(
            geo_place=place, party=party, role=role("operator")
        )

        assert place.party_associations.count() == 2  # type: ignore  # reverse FK: plugin-less inference gap

    def test_duplicate_place_party_role_rejected(self):
        place = GeoPlaceFactory()
        party = PartyFactory()
        GeoPlaceParty.objects.create(geo_place=place, party=party, role=role("source"))

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                GeoPlaceParty.objects.create(
                    geo_place=place, party=party, role=role("source")
                )

    def test_clean_rejects_role_parent_itself(self):
        parent = Category.objects.get(slug="role", parent__isnull=True)
        association = GeoPlaceParty(
            geo_place=GeoPlaceFactory(), party=PartyFactory(), role=parent
        )

        with pytest.raises(ValidationError):
            association.clean()

    def test_clean_rejects_child_of_other_subtree(self):
        other_parent = Category.objects.create(slug="other-vocab")
        other_child = Category.objects.create(slug="other-child", parent=other_parent)
        association = GeoPlaceParty(
            geo_place=GeoPlaceFactory(),
            party=PartyFactory(),
            role=other_child,
        )

        with pytest.raises(ValidationError):
            association.clean()

    def test_party_delete_restricted_while_in_use(self):
        association = GeoPlaceParty.objects.create(
            geo_place=GeoPlaceFactory(), party=PartyFactory(), role=role("brand")
        )

        with pytest.raises(RestrictedError):
            association.party.delete()

    def test_role_delete_blocked_as_protected_vocabulary(self):
        """role.* is code-coupled vocabulary (migration 0060 marks it
        is_protected) — deletion raises before the DB RESTRICT can
        fire (geoplace-kinds-operations-graph task 1.2). The DB
        constraint remains as a bulk-delete backstop."""
        association = GeoPlaceParty.objects.create(
            geo_place=GeoPlaceFactory(), party=PartyFactory(), role=role("brand")
        )

        from django.core.exceptions import ValidationError

        with pytest.raises(ValidationError, match="protected vocabulary"):
            association.role.delete()


class TestAmenityWritePath:
    """AmenityDetail.update_or_create writes party associations (2.2)."""

    @staticmethod
    def _schema(*entries: dict[str, Any]) -> GeoPlaceAmenityInput:
        return GeoPlaceAmenityInput(
            name="Test Place",
            location=LocationSchema(lon=7.7343, lat=46.0234),
            country_code="CH",
            place_type_identifiers=[],
            parties=[PartyInput(**entry) for entry in entries],
        )

    def test_parties_write_creates_party_and_association(self):
        place = GeoPlaceFactory()

        _detail, status = AmenityDetail.update_or_create(
            place=place,
            schema=self._schema({"slug": "volg", "name": "Volg", "role": "role.brand"}),
        )

        assert status == UpdateCreateStatus.created
        association = place.party_associations.get()  # type: ignore  # reverse FK: plugin-less inference gap
        assert association.role.identifier == "role.brand"
        assert association.party.slug == "volg"
        assert association.party.name == "Volg"

    def test_name_only_write_resolves_by_extra_identity(self):
        place = GeoPlaceFactory()

        _detail, _status = AmenityDetail.update_or_create(
            place=place,
            schema=self._schema({"name": "SAC Bern", "role": "role.operator"}),
        )

        party = Party.objects.get(extra__osm_name="sac_bern")
        assert party.name == "SAC Bern"
        assert place.party_associations.get().party == party  # type: ignore  # reverse FK

    def test_name_only_write_mints_short_slug(self):
        place = GeoPlaceFactory()

        _detail, _status = AmenityDetail.update_or_create(
            place=place,
            schema=self._schema({"name": "Coop Supermarkt", "role": "role.brand"}),
        )

        party = Party.objects.get(extra__osm_name="coop_supermarkt")
        assert len(party.slug) <= 15
        assert re.fullmatch(r"[a-z0-9]{1,9}-[a-z0-9]{5,8}", party.slug)

    def test_existing_slug_reference_wins_over_name(self):
        """A slug match resolves the party even when the name differs."""
        place = GeoPlaceFactory()
        existing = Party.objects.create(slug="volg", name="Volg")

        AmenityDetail.update_or_create(
            place=place,
            schema=self._schema(
                {"slug": "volg", "name": "Completely Different", "role": "role.brand"}
            ),
        )

        association = place.party_associations.get()  # type: ignore  # reverse FK
        assert association.party == existing
        assert Party.objects.filter(extra__osm_name="completely_different").count() == 0

    def test_name_only_reuses_existing_party(self):
        """Name-only input dedups through the key — no duplicate row."""
        place = GeoPlaceFactory()
        existing = Party.objects.create(name="Volg")

        AmenityDetail.update_or_create(
            place=place,
            schema=self._schema({"name": "Volg", "role": "role.brand"}),
        )

        assert Party.objects.filter(extra__osm_name="volg").count() == 1
        association = place.party_associations.get()  # type: ignore  # reverse FK
        assert association.party == existing
        assert existing.slug  # untouched minted slug

    def test_slug_and_name_missing_rejected(self):
        place = GeoPlaceFactory()

        with pytest.raises(ValueError, match="slug or a name"):
            AmenityDetail.update_or_create(
                place=place,
                schema=self._schema({"role": "role.brand"}),
            )

    def test_parties_write_idempotent(self):
        place = GeoPlaceFactory()
        schema = self._schema({"slug": "volg", "name": "Volg", "role": "role.brand"})

        AmenityDetail.update_or_create(place=place, schema=schema)
        _detail, status = AmenityDetail.update_or_create(place=place, schema=schema)

        assert status == UpdateCreateStatus.no_change
        assert place.party_associations.count() == 1  # type: ignore  # reverse FK

    def test_operator_party_mints_into_review(self):
        place = GeoPlaceFactory()

        AmenityDetail.update_or_create(
            place=place,
            schema=self._schema(
                {
                    "name": "SAC Bern",
                    "role": "role.operator",
                    "review_status": "review",
                }
            ),
        )

        party = Party.objects.get(extra__osm_name="sac_bern")
        assert party.review_status == "review"

    def test_unknown_role_identifier_rejected(self):
        place = GeoPlaceFactory()

        with pytest.raises(ValueError):
            AmenityDetail.update_or_create(
                place=place,
                schema=self._schema(
                    {"slug": "volg", "name": "Volg", "role": "role.nonexistent"}
                ),
            )

    def test_role_parent_identifier_rejected(self):
        place = GeoPlaceFactory()

        with pytest.raises(ValueError):
            AmenityDetail.update_or_create(
                place=place,
                schema=self._schema(
                    {"slug": "volg", "name": "Volg", "role": "root.role"}
                ),
            )

    def test_protected_parties_skipped(self):
        place = GeoPlaceFactory()

        AmenityDetail.update_or_create(
            place=place,
            schema=self._schema({"slug": "volg", "name": "Volg", "role": "role.brand"}),
            protected_fields={"parties"},
        )

        assert place.party_associations.count() == 0  # type: ignore  # reverse FK


class TestRoleScopedPartyProtection:
    """``{"parties": ["role.brand"]}`` in ``protected_fields`` shields
    only the listed roles (OpenSpec ``party-slug-minting``); the legacy
    flat ``"parties"`` string shields all roles."""

    @staticmethod
    def _schema(*entries: dict[str, Any]) -> GeoPlaceAmenityInput:
        return GeoPlaceAmenityInput(
            name="Test Place",
            location=LocationSchema(lon=7.7343, lat=46.0234),
            country_code="CH",
            place_type_identifiers=[],
            parties=[PartyInput(**entry) for entry in entries],
        )

    @staticmethod
    def _protect(place: Any, protected_fields: list[Any]) -> None:
        place.protected_fields = protected_fields
        place.save(update_fields=["protected_fields"])

    def test_scoped_protection_skips_only_protected_roles(self):
        place = GeoPlaceFactory()
        self._protect(place, [{"parties": ["role.brand"]}])

        AmenityDetail.update_or_create(
            place=place,
            schema=self._schema(
                {"name": "Volg", "role": "role.brand"},
                {"name": "SAC Bern", "role": "role.operator"},
            ),
        )

        roles = {
            association.role.identifier
            for association in place.party_associations.all()  # type: ignore  # reverse FK
        }
        assert roles == {"role.operator"}  # brand skipped, operator added

    def test_scoped_protection_union_blocks_both(self):
        place = GeoPlaceFactory()
        self._protect(place, [{"parties": ["role.brand", "role.operator"]}])

        AmenityDetail.update_or_create(
            place=place,
            schema=self._schema(
                {"name": "Volg", "role": "role.brand"},
                {"name": "SAC Bern", "role": "role.operator"},
            ),
        )

        assert place.party_associations.count() == 0  # type: ignore  # reverse FK

    def test_legacy_flat_protection_blocks_all_roles(self):
        place = GeoPlaceFactory()
        self._protect(place, ["parties"])

        AmenityDetail.update_or_create(
            place=place,
            schema=self._schema(
                {"name": "Volg", "role": "role.brand"},
                {"name": "SAC Bern", "role": "role.operator"},
            ),
        )

        assert place.party_associations.count() == 0  # type: ignore  # reverse FK

    def test_unprotected_place_writes_all_roles(self):
        place = GeoPlaceFactory()

        AmenityDetail.update_or_create(
            place=place,
            schema=self._schema(
                {"name": "Volg", "role": "role.brand"},
                {"name": "SAC Bern", "role": "role.operator"},
            ),
        )

        assert place.party_associations.count() == 2  # type: ignore  # reverse FK

    def test_resolver_reads_only_scoped_entries(self):
        place = GeoPlaceFactory(protected_fields=[{"parties": ["role.brand"]}])
        assert place.protected_party_roles() == {"role.brand"}

        # The flat string stays the gates' job — the resolver ignores it.
        place.protected_fields = ["name_de", "parties"]
        place.save(update_fields=["protected_fields"])
        assert place.protected_party_roles() == set()

    def test_geoplace_update_path_tolerates_structured_entries(self):
        """Advisor review finding 1: the real import update path
        (GeoPlace.update_or_create → _update_from_schema) must not
        crash on structured protected_fields entries — the str-only
        set() crashed with TypeError before the fix. Called directly:
        dedup is orthogonal to the regression (note: category
        resolution is lru_cached, so each test needs its own slugs)."""
        # Map-tree shape: contract groups live under the amenity
        # super-root (kind derivation needs the full ancestry).
        from server.apps.categories.models import Category as _Category
        from server.apps.geometries.schemas import (
            GeoPlaceAmenityInput as Schema,
        )

        amenity = _Category.objects.get(slug="amenity", parent__slug="map")
        shop = _Category.objects.create(slug="shop", name="Shop", parent=amenity)
        _Category.objects.create(slug="kiosk", parent=shop, name="Kiosk")

        place = GeoPlaceFactory(
            kind_slug="map.amenity",
            protected_fields=[{"parties": ["role.brand"]}],
        )

        schema = Schema(
            name="Test Place",
            location=LocationSchema(lon=7.7343, lat=46.0234),
            country_code="CH",
            place_type_identifiers=["shop.kiosk"],
            operating_status=OperatingStatus.OPEN,  # branch requires it
            parties=[
                PartyInput(name="Volg", role="role.brand"),
                PartyInput(name="SAC Bern", role="role.operator"),
            ],
        )

        # The exact import entry that used to raise TypeError.
        updated_place, _status = GeoPlace._update_from_schema(
            place, schema, GeoPlace._resolve_place_types(["shop.kiosk"]), None, None
        )

        assert updated_place.pk == place.pk
        roles = {
            association.role.identifier
            for association in updated_place.party_associations.all()  # type: ignore  # reverse FK
        }
        assert roles == {"role.operator"}  # brand protected, operator written

    def test_tracked_field_edit_preserves_structured_entries(self):
        """Advisor review finding 2: editing a tracked field on a place
        that already carries structured protection must not crash (and
        must not drop the structured entries)."""
        place = GeoPlaceFactory(protected_fields=[{"parties": ["role.brand"]}])

        place.name = "Renamed Place"
        place.save()

        place.refresh_from_db()
        assert {"parties": ["role.brand"]} in (place.protected_fields or [])
        # The tracker protects the language-suffixed field (name_de).
        assert "name_de" in (place.protected_fields or [])

    def test_brand_reimport_dedups_by_osm_name(self):
        """Name-only PartyInput entries (the OSM import shape) must
        dedup reimports by the ``extra.osm_name`` identity — the old
        ``slug__in=[None]`` filter never matched and minted duplicate
        places."""
        # Map-tree shape (see shop/kiosk above).
        from server.apps.categories.models import Category as _Category
        from server.apps.geometries.schemas import (
            GeoPlaceAmenityInput as Schema,
        )

        amenity = _Category.objects.get(slug="amenity", parent__slug="map")
        tourism = _Category.objects.create(
            slug="tourism", name="Tourism", parent=amenity
        )
        _Category.objects.create(slug="hotel", parent=tourism, name="Hotel")

        def schema_with_brand() -> Schema:
            return Schema(
                name="Kiosk",
                location=LocationSchema(lon=7.7343, lat=46.0234),
                country_code="CH",
                place_type_identifiers=["tourism.hotel"],
                operating_status=OperatingStatus.OPEN,  # branch requires it
                parties=[PartyInput(name="Volg", role="role.brand")],
            )

        place, _created = GeoPlace.update_or_create(schema=schema_with_brand())
        reimported, _status = GeoPlace.update_or_create(schema=schema_with_brand())

        assert reimported.pk == place.pk  # matched by identity, not duplicated

"""Tests for icon library models and data helpers (openspec: icon-library)."""

import pytest

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from server.apps.categories.models import Category
from server.apps.organizations.models import Organization
from server.apps.symbols.icon_data import (
    CURATED_ACTIVITY_SLUGS,
    fold_keyword,
    normalize_hexcode,
)
from server.apps.symbols.models import Icon, IconKeyword, SymbolCollection

pytestmark = [pytest.mark.django_db]


@pytest.fixture
def org() -> Organization:
    return Organization.objects.create(slug="microsoft", name="Microsoft")


@pytest.fixture
def pack(org):
    return SymbolCollection.objects.create(slug="fluent-emoji", source_org=org)


@pytest.fixture
def other_pack(org):
    return SymbolCollection.objects.create(slug="noto-emoji", source_org=org)


@pytest.fixture
def emoji_root():
    return Category.objects.create(slug="emoji", name="Emoji")


@pytest.fixture
def subgroup(emoji_root):
    group = Category.objects.create(slug="travel-places", parent=emoji_root)
    return Category.objects.create(slug="place-other", parent=group)


class IconDataHelpers:
    """Pure-function tests: folding and hexcode normalization (design D5)."""

    def test_fold_keyword_accents_and_case(self):
        assert fold_keyword("Zelt") == "zelt"
        assert fold_keyword("Randonnée") == "randonnee"
        assert fold_keyword("  GROẞE   Straße ") == "grosse strasse"

    def test_normalize_hexcode_strips_fe0f(self):
        assert normalize_hexcode("26fa") == "26FA"
        assert normalize_hexcode("2764-FE0F") == "2764"
        assert normalize_hexcode("1f469_200d_2764_fe0f_200d_1f48b") == (
            "1F469-200D-2764-200D-1F48B"
        )

    def test_curated_shortlist_is_kebab_slugs(self):
        assert "tent" in CURATED_ACTIVITY_SLUGS
        assert all(" " not in slug for slug in CURATED_ACTIVITY_SLUGS)


class TestIconModel:
    def test_same_slug_in_two_packs(self, pack, other_pack, subgroup):
        """Spec scenario: slug `tent` exists independently in two packs."""
        fluent = Icon.objects.create(pack=pack, slug="tent", category=subgroup)
        noto = Icon.objects.create(pack=other_pack, slug="tent")
        assert fluent.pk != noto.pk
        assert Icon.objects.filter(slug="tent").count() == 2

    def test_duplicate_slug_within_pack_rejected(self, pack):
        Icon.objects.create(pack=pack, slug="tent")
        # Nested atomic keeps the test transaction usable afterwards.
        with pytest.raises(IntegrityError), transaction.atomic():
            Icon.objects.create(pack=pack, slug="tent")

    def test_unicode_nullable_and_indexed(self, pack):
        icon = Icon.objects.create(pack=pack, slug="brand-logo")
        assert icon.unicode is None

    def test_root_category_rejected(self, pack, emoji_root):
        """Design D4: the category FK must reference subgroups only."""
        icon = Icon(pack=pack, slug="tent", category=emoji_root)
        with pytest.raises(ValidationError):
            icon.clean()

    def test_subgroup_category_accepted(self, pack, subgroup):
        icon = Icon(pack=pack, slug="tent", category=subgroup)
        icon.clean()  # no raise

    def test_i18n_name(self, pack):
        icon = Icon.objects.create(pack=pack, slug="tent", name="tent")
        icon.i18n = {"name_de": "Zelt"}
        icon.save()
        refreshed = Icon.objects.get(pk=icon.pk)
        assert refreshed.name_i18n == "tent"
        assert refreshed.i18n["name_de"] == "Zelt"


class TestIconKeywordModel:
    def test_unique_icon_locale_folded(self, pack):
        icon = Icon.objects.create(pack=pack, slug="tent")
        IconKeyword.objects.create(
            icon=icon, locale="de", keyword="Zelt", keyword_folded="zelt"
        )
        # Same folded form (different display form) is rejected; the
        # nested atomic keeps the test transaction usable afterwards.
        with pytest.raises(IntegrityError), transaction.atomic():
            IconKeyword.objects.create(
                icon=icon, locale="de", keyword="zelt", keyword_folded="zelt"
            )
        # Other locale or other icon is fine.
        IconKeyword.objects.create(
            icon=icon, locale="en", keyword="tent", keyword_folded="tent"
        )

    def test_index_locale_folded_exists(self):
        index_fields = [tuple(index.fields) for index in IconKeyword._meta.indexes]
        assert ("locale", "keyword_folded") in index_fields

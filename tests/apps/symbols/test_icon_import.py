"""Tests for the icon_import command (openspec: icon-library).

Runs against the shared small upstream-shaped fixture tree
(``tests/apps/symbols/conftest.py``, ``--data-dir``) — no network.
"""

from io import StringIO
from pathlib import Path

import pytest

from django.core.management import call_command

from server.apps.categories.models import Category
from server.apps.licenses.models import License
from server.apps.organizations.models import Organization
from server.apps.symbols.models import (
    Icon,
    IconCuratedList,
    IconCuratedListEntry,
    IconKeyword,
    Symbol,
    SymbolCollection,
)

pytestmark = [pytest.mark.django_db]


def _run(
    root: Path, source: str = "fluent", ref: str = "test-ref", extra: tuple = ()
) -> str:
    """Run one icon_import invocation for the given source."""
    out = StringIO()
    call_command(
        "icon_import",
        "--source",
        source,
        "--ref",
        ref,
        "--locales",
        "de,en",
        "--data-dir",
        str(root),
        *extra,
        stdout=out,
    )
    return out.getvalue()


def _run_fluent_only(root: Path, extra: tuple = ()) -> str:
    return _run(root, source="fluent", ref="test-ref", extra=extra)


def _run_both(root: Path, extra: tuple = ()) -> str:
    """Import both packs (two source invocations)."""
    return _run(root, source="fluent", ref="test-ref", extra=extra) + _run(
        root, source="noto", ref="noto-ref", extra=extra
    )


class TestFullImport:
    """First run at a fresh database."""

    @pytest.fixture(autouse=True)
    def _imported(self, emoji_fixture):
        self.output = _run_both(emoji_fixture)

    def test_packs_refs_licenses_orgs_recorded(self):
        fluent = SymbolCollection.objects.get(slug="fluent-emoji")
        noto = SymbolCollection.objects.get(slug="noto-emoji")
        assert fluent.extra["ref"] == "test-ref"
        assert noto.extra["ref"] == "noto-ref"
        assert fluent.source_org.slug == "microsoft"
        assert noto.source_org.slug == "google"
        assert License.objects.filter(slug__in=["mit", "apache-2-0"]).count() == 2
        assert (
            Organization.objects.filter(slug__in=["microsoft", "google"]).count() == 2
        )

    def test_fluent_icon_full_import(self):
        icon = Icon.objects.get(pack__slug="fluent-emoji", slug="tent")
        assert icon.unicode == "26FA"
        assert icon.name == "tent"
        # CLDR subgroup reference, group one join up (design D4).
        assert icon.category.slug == "place-other"
        assert icon.category.parent.slug == "travel-places"
        assert icon.category.parent.parent.slug == "emoji"
        # 3 styles per fluent icon: detailed/simple/mono (design D1).
        assert set(
            Symbol.objects.filter(slug="fluent-emoji-tent").values_list(
                "style", flat=True
            )
        ) == {"detailed", "simple", "mono"}
        assert icon.symbol_detailed.style == "detailed"
        assert icon.symbol_simple.style == "simple"
        assert icon.symbol_mono.style == "mono"
        assert icon.symbol_detailed.svg_file

    def test_fe0f_stripped_hexcode_join(self):
        """emojibase '2764-FE0F' joins fluent metadata '2764'."""
        icon = Icon.objects.get(pack__slug="fluent-emoji", slug="red-heart")
        assert icon.unicode == "2764"
        assert icon.keywords.filter(  # pyright: ignore[reportAttributeAccessIssue]  # reverse FK: django-stubs gap
            locale="en", keyword_folded="red heart"
        ).exists()

    def test_skin_tone_layout(self):
        assert Icon.objects.filter(
            pack__slug="fluent-emoji", slug="hiking-boot"
        ).exists()
        assert set(
            Symbol.objects.filter(slug="fluent-emoji-hiking-boot").values_list(
                "style", flat=True
            )
        ) == {"detailed", "simple", "mono"}

    def test_import_does_not_touch_curation(self):
        """Curation is admin data: the import creates no memberships.

        (The seeded ``activities`` list itself comes from a migration,
        not from the import; in tests it has no entries since the seed
        runs before any icons exist.)
        """
        assert IconCuratedListEntry.objects.count() == 0
        curated_list = IconCuratedList.objects.filter(slug="activities").first()
        assert curated_list is not None
        assert not curated_list.icons.exists()

    def test_component_entries_skipped(self):
        """ZWJ etc. (the `component` group) never become icons."""
        assert not Icon.objects.filter(slug="zero-width-joiner").exists()

    def test_unmatched_icon_imported_without_keywords(self):
        icon = Icon.objects.get(pack__slug="fluent-emoji", slug="brand-logo")
        assert icon.unicode == "E000"
        assert icon.category is None
        assert not icon.keywords.exists()  # pyright: ignore[reportAttributeAccessIssue]  # reverse FK: django-stubs gap
        assert "brand-logo" in self.output

    def test_noto_pack_single_style_same_slug(self):
        """Noto imports color→detailed only; slug parity across packs."""
        icon = Icon.objects.get(pack__slug="noto-emoji", slug="tent")
        assert icon.unicode == "26FA"
        assert set(
            Symbol.objects.filter(slug="noto-emoji-tent").values_list(
                "style", flat=True
            )
        ) == {"detailed"}

    def test_noto_unmatched_slug_fallback(self):
        icon = Icon.objects.get(pack__slug="noto-emoji", slug="emoji-0023")
        assert not icon.keywords.exists()  # pyright: ignore[reportAttributeAccessIssue]  # reverse FK: django-stubs gap

    def test_keywords_folded_and_localized(self):
        icon = Icon.objects.get(pack__slug="fluent-emoji", slug="tent")
        folded = set(
            icon.keywords.values_list("locale", "keyword_folded")  # pyright: ignore[reportAttributeAccessIssue]  # reverse FK: django-stubs gap
        )
        assert folded == {
            ("en", "tent"),
            ("en", "camping"),
            ("de", "zelt"),
            ("de", "campen"),
            ("de", "zelten"),
        }
        keyword = icon.keywords.get(  # pyright: ignore[reportAttributeAccessIssue]  # reverse FK: django-stubs gap
            locale="de", keyword_folded="zelt"
        )
        assert keyword.keyword == "Zelt"

    def test_taxonomy_localized_and_idempotent_shape(self):
        group = Category.objects.get(slug="travel-places", parent__slug="emoji")
        assert group.i18n["name_de"] == "Reisen & Orte"
        subgroup = Category.objects.get(slug="place-other", parent=group)
        assert subgroup.i18n["name_de"] == "andere Orte"
        # Root has no parent; icons point at subgroups only.
        assert group.parent.slug == "emoji"
        assert Category.objects.filter(slug="emoji", parent=None).count() == 1


class TestIdempotentRerun:
    """Re-running at the same ref creates no duplicates (spec)."""

    def test_rerun_creates_nothing(self, emoji_fixture):
        _run_both(emoji_fixture)
        counts = {
            Icon: Icon.objects.count(),
            Symbol: Symbol.objects.count(),
            IconKeyword: IconKeyword.objects.count(),
            Category: Category.objects.count(),
            SymbolCollection: SymbolCollection.objects.count(),
        }
        output = _run_both(emoji_fixture)
        assert Icon.objects.count() == counts[Icon]
        assert Symbol.objects.count() == counts[Symbol]
        assert IconKeyword.objects.count() == counts[IconKeyword]
        assert Category.objects.count() == counts[Category]
        assert SymbolCollection.objects.count() == counts[SymbolCollection]
        assert "icons_created: 0" in output
        assert "keywords_created: 0" in output
        assert "symbols_created: 0" in output
        assert "categories_created: 0" in output

    def test_taxonomy_rerun_no_duplicate_categories(self, emoji_fixture):
        _run_both(emoji_fixture)
        _run_both(emoji_fixture)
        assert Category.objects.filter(slug="emoji", parent=None).count() == 1
        assert Category.objects.filter(slug="travel-places").count() == 1
        assert Category.objects.filter(slug="place-other").count() == 1


class TestRerunPreservesCuration:
    def test_curated_membership_survives_rerun(self, emoji_fixture):
        """Curation is separate data: re-imports never clobber it."""
        _run_fluent_only(emoji_fixture)
        # The seeded default list (migration) — as the admin would use it.
        curated_list = IconCuratedList.objects.get_or_create(
            slug="activities", defaults={"name": "Activities"}
        )[0]
        icon = Icon.objects.get(pack__slug="fluent-emoji", slug="tent")
        IconCuratedListEntry.objects.create(curated_list=curated_list, icon=icon)

        _run_fluent_only(emoji_fixture)

        icon.refresh_from_db()
        assert list(curated_list.icons.values_list("slug", flat=True)) == ["tent"]


class TestDryRun:
    def test_dry_run_writes_nothing(self, emoji_fixture):
        _run_both(emoji_fixture, extra=("--dry-run",))
        assert Icon.objects.count() == 0
        assert Symbol.objects.count() == 0
        assert IconKeyword.objects.count() == 0
        assert SymbolCollection.objects.count() == 0

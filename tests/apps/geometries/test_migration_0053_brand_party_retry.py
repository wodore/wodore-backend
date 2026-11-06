"""Pin the 0053 brand→party short-slug collision retry.

Claude review suggestion: the in-place 0053 fix mints short party
slugs for long brand category slugs with a bounded 3-attempt retry on
unique collisions. The historical ``AmenityDetail.brand`` column no
longer exists on the live model, so the migration function is driven
through a mock apps registry (its ``apps`` argument) — only the retry
semantics are under test, not the ORM.
"""

import importlib
from typing import Any
from unittest.mock import MagicMock

from django.db import IntegrityError

mig = importlib.import_module(
    "server.apps.geometries.migrations.0053_brand_categories_to_parties"
)


def _mock_apps(
    detail: Any, party_model: MagicMock, gpp_model: MagicMock, role_brand: Any
) -> MagicMock:
    """An ``apps`` registry mock shaped like RunPython's StateApps."""
    models = {
        ("geometries", "AmenityDetail"): detail,
        ("parties", "Party"): party_model,
        ("geometries", "GeoPlaceParty"): gpp_model,
        ("categories", "Category"): role_brand,
    }

    def get_model(app_label: str, model_name: str) -> Any:
        if (app_label, model_name) == ("categories", "Category"):
            return category_model
        return models[(app_label, model_name)]

    category_model = MagicMock()
    category_model.objects.get.return_value = role_brand

    apps = MagicMock()
    apps.get_model.side_effect = get_model
    return apps


class TestBrandPartySlugRetry:
    def test_long_slug_mints_with_bounded_retry(self):
        detail = MagicMock()
        detail.brand.slug = "a-brand-category-slug-longer-than-fifteen"
        detail.brand.name = "Long Brand"
        detail.brand.i18n = {"name_en": "Long Brand"}
        detail.geo_place_id = 1

        detail_model = MagicMock()
        detail_model.objects.exclude.return_value.select_related.return_value = [detail]

        party_model = MagicMock()
        successful_party = MagicMock()
        party_model.objects.create.side_effect = [
            IntegrityError("slug collision"),
            IntegrityError("slug collision"),
            successful_party,
        ]
        gpp_model = MagicMock()

        role_brand = MagicMock(identifier="role.brand")
        apps = _mock_apps(detail_model, party_model, gpp_model, role_brand)

        mig.convert_brand_to_party(apps, None)

        # bounded retry: exactly three mint attempts, third wins
        assert party_model.objects.create.call_count == 3
        minted_slugs = [
            call.kwargs["slug"] for call in party_model.objects.create.call_args_list
        ]
        assert all(len(slug) <= 15 for slug in minted_slugs)
        # the original brand slug is preserved for re-derivation
        assert (
            party_model.objects.create.call_args.kwargs["extra"]["brand_slug"]
            == "a-brand-category-slug-longer-than-fifteen"
        )
        # the association is written against the successfully minted party
        gpp_model.objects.get_or_create.assert_called_once_with(
            geo_place_id=1, party=successful_party, role=role_brand
        )

    def test_retry_exhausted_raises(self):
        detail = MagicMock()
        detail.brand.slug = "a-brand-category-slug-longer-than-fifteen"
        detail.brand.name = "Long Brand"
        detail.brand.i18n = {"name_en": "Long Brand"}
        detail.geo_place_id = 1

        detail_model = MagicMock()
        detail_model.objects.exclude.return_value.select_related.return_value = [detail]

        party_model = MagicMock()
        party_model.objects.create.side_effect = IntegrityError("always collides")
        gpp_model = MagicMock()

        apps = _mock_apps(
            detail_model, party_model, gpp_model, MagicMock(identifier="role.brand")
        )

        try:
            mig.convert_brand_to_party(apps, None)
        except RuntimeError as exc:
            assert "could not mint" in str(exc)
        else:
            raise AssertionError("RuntimeError expected after 3 failed attempts")
        gpp_model.objects.get_or_create.assert_not_called()

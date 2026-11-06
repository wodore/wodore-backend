"""Unit tests for the generic short-slug minting helper.

OpenSpec change ``party-slug-minting`` (task 1.1): ``mint_short_slug``
is the verbatim extraction of ``GeoPlace.generate_unique_slug``'s
algorithm — deterministic readable base (slugify, ignore words, <= 3
words over a ~9-char target), random ``[a-z0-9]`` suffix sized 5-8 from
the remaining space, result clamped to ``max_length``.
"""

import re

from server.apps.geometries.models import GeoPlace
from server.core.utils import mint_short_slug

#: Minted shape: 1-9 lowercase-alnum base, hyphen, 5-8 char suffix.
MINTED = re.compile(r"^[a-z0-9]{1,9}-[a-z0-9]{5,8}$")


class TestMintShortSlug:
    def test_long_name_truncates_readably(self):
        slug = mint_short_slug("Liechtensteinisches Landesspital")
        # 2 words: chars_per_word = 9 // 2 = 4 -> "liec" + "land",
        # remaining 1 extends the first word -> base "liechland".
        assert slug.startswith("liechland-")
        assert MINTED.fullmatch(slug)
        assert len(slug) <= 15

    def test_two_short_words(self):
        slug = mint_short_slug("SAC Bern")
        # base "sacbern" (7 chars) leaves room for a 7-char suffix.
        assert slug.startswith("sacbern-")
        assert MINTED.fullmatch(slug)
        assert len(slug) == 15

    def test_single_word(self):
        slug = mint_short_slug("Migros")
        assert slug.startswith("migros-")
        assert MINTED.fullmatch(slug)

    def test_short_name_gets_longest_suffix(self):
        slug = mint_short_slug("Lio")
        # base "lio" -> available space 11 -> suffix capped at 8.
        assert slug.startswith("lio-")
        assert len(slug) == 3 + 1 + 8

    def test_empty_name_uses_fallback(self):
        assert mint_short_slug("", fallback="party").startswith("party-")
        assert mint_short_slug("   ", fallback="party").startswith("party-")

    def test_ignored_words_fall_back(self):
        slug = mint_short_slug(
            "Hotel Restaurant",
            fallback="place",
            ignore_words={"hotel", "restaurant"},
        )
        assert slug.startswith("place-")
        assert MINTED.fullmatch(slug)

    def test_partial_ignore_keeps_rest(self):
        slug = mint_short_slug("Gasthaus Panorama", ignore_words={"gasthaus"})
        assert slug.startswith("panorama-")

    def test_short_words_below_min_length_dropped(self):
        # "de" and "la" are below the 3-char minimum; the base comes
        # from the remaining words ("refu"+"marm", first word extended
        # by the leftover char -> "refugmarm").
        slug = mint_short_slug("Refuge de la Marmotte")
        assert slug.startswith("refugmarm-")

    def test_two_mints_differ_in_suffix(self):
        first = mint_short_slug("Migros")
        second = mint_short_slug("Migros")
        assert first.split("-")[0] == second.split("-")[0]
        assert first != second

    def test_suffix_is_lowercase_alnum(self):
        for _ in range(25):
            suffix = mint_short_slug("Coop").split("-")[1]
            assert suffix == suffix.lower()
            assert suffix.isalnum()

    def test_custom_max_length(self):
        slug = mint_short_slug("Migros", max_length=20)
        assert len(slug) == 6 + 1 + 8  # suffix capped at 8

    def test_result_never_exceeds_max_length(self):
        for name in ("A very long place name indeed", "X", "", "Ünïcödé Nàme"):
            assert len(mint_short_slug(name, fallback="place")) <= 15


class TestGeoPlaceDelegation:
    """``generate_unique_slug`` is a thin wrapper (task 1.2): the
    geoplace specifics (amenity ignore words, category fallback) are
    arguments, the outputs keep the algorithm's behavior."""

    def test_delegates_with_geoplace_specifics(self):
        assert GeoPlace.generate_unique_slug("Gasthaus Panorama").startswith(
            "panorama-"
        )  # amenity word filtered

    def test_category_fallback(self):
        assert GeoPlace.generate_unique_slug("", "drinkwater").startswith("drinkwater-")

    def test_default_fallback(self):
        assert GeoPlace.generate_unique_slug("").startswith("place-")

    def test_shape_and_length(self):
        for name in ("Liechtensteinisches Landesspital", "Lio", "Adolf Bike Shop"):
            slug = GeoPlace.generate_unique_slug(name)
            assert MINTED.fullmatch(slug)
            assert len(slug) <= 15

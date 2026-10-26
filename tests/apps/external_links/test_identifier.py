"""Identifier minting for external links (savepoint-retry idiom).

The probe-based generation was replaced by a pure mint plus a
savepoint-retry on the unique constraint (mirrors Party.save /
GeoPlace.save from party-slug-minting).
"""

from __future__ import annotations

import re

import pytest

from django.db import IntegrityError

from server.apps.external_links.models import ExternalLink

pytestmark = [pytest.mark.django_db]

MINTED = re.compile(r"^[a-z0-9]{6}$")


class TestIdentifierMinting:
    def test_mint_shape(self) -> None:
        assert MINTED.fullmatch(ExternalLink.generate_unique_identifier())
        assert len(ExternalLink.generate_unique_identifier(length=8)) == 8

    def test_save_mints_identifier(self) -> None:
        # tel: URLs skip all web-only side effects (source detection,
        # title extraction, health checks).
        link = ExternalLink(url="tel:+4179000000")
        link.save(skip_health_check=True)

        assert MINTED.fullmatch(link.identifier)

    def test_explicit_identifier_kept(self) -> None:
        link = ExternalLink(url="tel:+4179000000", identifier="custom1")
        link.save(skip_health_check=True)

        assert link.identifier == "custom1"

    def test_collision_remints_and_retries(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ExternalLink.objects.create(url="tel:+4179000001", identifier="aaaa11")

        minted = iter(["aaaa11", "bbbb22"])

        def fake_mint(*_args: object, **_kwargs: object) -> str:
            return next(minted)

        monkeypatch.setattr(ExternalLink, "generate_unique_identifier", fake_mint)

        link = ExternalLink(url="tel:+4179000002")
        link.save(skip_health_check=True)

        assert link.identifier == "bbbb22"
        assert ExternalLink.objects.count() == 2

    def test_exhausted_retries_raise(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ExternalLink.objects.create(url="tel:+4179000001", identifier="aaaa11")

        def fake_mint(*_args: object, **_kwargs: object) -> str:
            return "aaaa11"

        monkeypatch.setattr(ExternalLink, "generate_unique_identifier", fake_mint)

        link = ExternalLink(url="tel:+4179000002")
        with pytest.raises(IntegrityError):
            link.save(skip_health_check=True)

    def test_explicit_collision_raises_without_remint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A colliding explicit identifier surfaces immediately — no
        pointless re-mint attempts."""
        ExternalLink.objects.create(url="tel:+4179000001", identifier="aaaa11")

        def fake_mint(*_args: object, **_kwargs: object) -> str:
            raise AssertionError("must not re-mint an explicit identifier")

        monkeypatch.setattr(ExternalLink, "generate_unique_identifier", fake_mint)

        link = ExternalLink(url="tel:+4179000002", identifier="aaaa11")
        with pytest.raises(IntegrityError):
            link.save(skip_health_check=True)

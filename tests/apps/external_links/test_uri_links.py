"""Tests for typed-URI external links (openspec: external-link-uris).

Covers the save-path kind derivation, scheme/kind consistency, the
NOT NULL invariant, non-web saves performing no network I/O, and the
per-kind health-check exemption (selector + check_health refusal).
"""

from __future__ import annotations

import pytest

from server.apps.categories.models import Category
from server.apps.external_links.models import ExternalLink
from server.apps.external_links.uri import validate_url_for_scheme

pytestmark = [pytest.mark.django_db]


def _kind(slug: str) -> Category:
    return Category.objects.get(parent__slug="uri", slug=slug)


class TestUriKindDerivation:
    def test_tel_url_derives_phone_kind(self):
        link = ExternalLink(url="tel:+41441234567", label="Reception")
        link.save()
        assert link.uri_kind.slug == "phone"

    def test_mailto_url_derives_email_kind(self):
        link = ExternalLink(url="mailto:info@wodore.com", label="Info")
        link.save()
        assert link.uri_kind.slug == "email"

    def test_http_url_derives_website_kind(self):
        link = ExternalLink(url="https://wodore.com", label="Home")
        link.save()
        assert link.uri_kind.slug == "website"

    def test_url_change_re_derives_kind(self):
        link = ExternalLink(url="tel:+41441234567", label="Reception")
        link.save()
        link.url = "https://wodore.com"
        link.save()
        assert link.uri_kind.slug == "website"

    def test_override_within_schemes_honored(self):
        link = ExternalLink(url="https://wodore.com", label="Home")
        link.save()
        link.url = "http://wodore.com/other"  # same kind, other scheme
        link.save()
        assert link.uri_kind.slug == "website"

    def test_unknown_scheme_rejected(self):
        from django.core.exceptions import ValidationError

        link = ExternalLink(url="ftp://example.com/x", label="Nope")
        with pytest.raises(ValidationError, match="no URI kind"):
            link.save()

    def test_kindless_save_rejected_after_not_null(self):
        # The vocabulary guarantees derivation; NOT NULL is the DB
        # guarantee — verified via the constraint on a raw insert.
        # atomic INSIDE pytest.raises so the savepoint rollback handles
        # the aborted transaction (the repo's constraint-test pattern).
        from django.db import IntegrityError, connection, transaction

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO external_links_externallink "
                        "(identifier, url, label, uri_kind_id, created, "
                        "modified) VALUES ('zztest', 'https://x.ch', 'x', "
                        "NULL, now(), now())"
                    )


class TestSchemeValidation:
    @pytest.mark.parametrize(
        "url",
        [
            "tel:+41441234567",
            "tel:0441234567",
            "mailto:a@b.ch",
            "https://wodore.com",
            "http://wodore.com/x?y=1",
        ],
    )
    def test_valid_urls_pass(self, url: str):
        validate_url_for_scheme(url)

    @pytest.mark.parametrize(
        "url",
        ["ftp://x.ch", "gopher://x", "tel:", "mailto:nope", "javascript:alert(1)"],
    )
    def test_invalid_urls_rejected(self, url: str):
        from django.core.exceptions import ValidationError

        with pytest.raises(ValidationError):
            validate_url_for_scheme(url)

    def test_clean_rejects_scheme_kind_mismatch(self):
        from django.core.exceptions import ValidationError

        link = ExternalLink(
            url="tel:+41441234567", label="Reception", uri_kind=_kind("website")
        )
        with pytest.raises(ValidationError):
            link.clean()

    def test_clean_scopes_kind_to_uri_parent(self):
        from django.core.exceptions import ValidationError

        alien = Category.objects.filter(parent__slug="role").first()
        assert alien is not None
        link = ExternalLink(url="tel:+41441234567", label="Reception", uri_kind=alien)
        with pytest.raises(ValidationError):
            link.clean()


class TestWebOnlyBehaviour:
    def test_tel_save_does_no_network_io(self, monkeypatch: pytest.MonkeyPatch):
        """Title extraction, source detection and health checks must
        not run for non-web URLs (no label forces the title path)."""
        import requests

        def _boom(*args: object, **kwargs: object) -> object:
            raise AssertionError("network I/O attempted for a tel: link")

        monkeypatch.setattr(requests, "get", _boom)
        monkeypatch.setattr(requests, "head", _boom)

        link = ExternalLink(url="tel:+41441234567")  # no label
        link.save()  # would fetch a title if ungated
        assert link.response_code is None
        assert link.last_checked is None

    def test_check_health_refuses_non_web(self):
        link = ExternalLink(url="mailto:info@wodore.com", label="Info")
        link.save()
        result = link.check_health()
        assert result.get("skipped") is True

    def test_health_selector_exempts_non_web_kinds(self):
        web = ExternalLink.objects.create(
            url="https://example.org", label="Web", uri_kind=_kind("website")
        )
        ExternalLink.objects.create(
            url="tel:+41441234567", label="Tel", uri_kind=_kind("phone")
        )
        # The same exclusion handle() applies — non-web kinds drop out.
        queryset = ExternalLink.objects.filter(is_active=True).exclude(
            uri_kind__extra__health_check=False
        )
        assert list(queryset.values_list("pk", flat=True)) == [web.pk]

"""ExternalAction tests (OpenSpec ``external-actions``).

Model constraints (partial uniques, D4), scoping semantics (D2/D3),
and the three API endpoints' contracts — public list filtering/CDN
cache headers, `/my/` auth rejection + private headers + own-rows-only,
render substitution/i18n/owner 404s (spec scenarios, review H3/H4).
"""

from __future__ import annotations

from typing import override

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import Client, TestCase, override_settings

from server.apps.categories.models import Category
from server.apps.external_links.models import ExternalAction, ExternalLink


def _link(
    url: str = "https://example.com/?q={name}", label: str = "Test"
) -> ExternalLink:
    link, _ = ExternalLink.objects.get_or_create(
        url=url,
        defaults={"label": label, "run_health_check": False},
    )
    link.save(skip_health_check=True)
    return link


def _kind(identifier: str = "map.transport") -> Category:
    """Get-or-create a kind category under the map root (by identifier)."""
    cat = Category.objects.filter(identifier=identifier).first()
    if cat is not None:
        return cat
    root, _ = Category.objects.get_or_create(
        slug="map", parent=None, defaults={"name": "Map"}
    )
    return Category.objects.create(
        slug=identifier.removeprefix("map."), parent=root, name=identifier
    )


class ExternalActionModelTests(TestCase):
    """Partial unique constraints and scoping validation (D2/D4)."""

    def test_public_duplicate_rejected(self) -> None:
        link = _link()
        ExternalAction.objects.create(link=link, user=None)
        with self.assertRaises(IntegrityError):
            ExternalAction.objects.create(link=link, user=None)

    def test_same_link_different_users_allowed(self) -> None:
        link = _link()
        user_a = get_user_model().objects.create(email="a@test.ch")  # type: ignore[no-untyped-call]  # manager factory method
        user_b = get_user_model().objects.create(email="b@test.ch")  # type: ignore[no-untyped-call]  # manager factory method
        ExternalAction.objects.create(link=link, user=user_a)
        ExternalAction.objects.create(link=link, user=user_b)
        self.assertEqual(ExternalAction.objects.count(), 2)

    def test_user_duplicate_rejected(self) -> None:
        link = _link()
        user = get_user_model().objects.create(email="a@test.ch")  # type: ignore[no-untyped-call]  # manager factory method
        ExternalAction.objects.create(link=link, user=user)
        with self.assertRaises(IntegrityError):
            ExternalAction.objects.create(link=link, user=user)

    def test_clean_rejects_non_map_kind(self) -> None:
        link = _link()
        other_root, _ = Category.objects.get_or_create(
            slug="other", parent=None, defaults={"name": "Other"}
        )
        non_map = Category.objects.create(
            slug="thing", parent=other_root, name="Non-map"
        )
        action = ExternalAction(link=link, user=None)
        action.save()
        action.kinds.add(non_map)
        with self.assertRaises(ValidationError):
            action.clean()

    def test_clean_rejects_lowercase_country(self) -> None:
        action = ExternalAction(link=_link(), user=None, countries=["ch"])
        with self.assertRaises(ValidationError):
            action.clean()


class ExternalActionsApiTests(TestCase):
    """The three endpoints' contracts (spec scenarios)."""

    @override
    def setUp(self) -> None:
        self.client = Client(SERVER_NAME="localhost")
        self.kind = _kind()
        self.public = ExternalAction.objects.create(
            link=_link("https://sbb.example/?from={name}", "SBB"),
            user=None,
            countries=["CH"],
            order=10,
        )
        self.public.kinds.add(self.kind)
        self.global_any = ExternalAction.objects.create(
            link=_link("https://maps.example/?ll={lat},{lon}", "Maps"),
            user=None,
            countries=[],
            order=100,
        )
        self.inactive = ExternalAction.objects.create(
            link=_link("https://gone.example/?x={name}", "Gone"),
            user=None,
            is_active=False,
        )
        self.user = get_user_model().objects.create(email="u1@test.ch")  # type: ignore[no-untyped-call]  # manager factory method
        self.user_action = ExternalAction.objects.create(
            link=_link("https://private.example/?q={name}", "Private"),
            user=self.user,
        )

    # ── Public list ─────────────────────────────────────────────────

    def test_kind_iso_filtering(self) -> None:
        r = self.client.get("/v1/links/actions?kind=map.transport&iso=CH")
        self.assertEqual(r.status_code, 200)
        ids = [row["id"] for row in r.json()]
        # transport-scoped SBB (CH) + the global any-point Maps
        self.assertIn(self.public.link.identifier, ids)
        self.assertIn(self.global_any.link.identifier, ids)
        self.assertNotIn(self.inactive.link.identifier, ids)

    def test_inactive_excluded(self) -> None:
        r = self.client.get("/v1/links/actions")
        ids = [row["id"] for row in r.json()]
        self.assertNotIn(self.inactive.link.identifier, ids)

    def test_iso_case_insensitive(self) -> None:
        r = self.client.get("/v1/links/actions?iso=ch")
        self.assertEqual(r.status_code, 200)
        ids = [row["id"] for row in r.json()]
        self.assertIn(self.public.link.identifier, ids)

    def test_lang_varies_labels(self) -> None:
        # Pin the modeltrans path: a localized label must actually be
        # served for that language (regression guard for the
        # label_i18n German-hardcode found in review).
        link = self.global_any.link
        link.label_fr = "Cartes"  # type: ignore  # dynamic attr: modeltrans column
        link.save(skip_health_check=True)
        ident = link.identifier

        def label_for(lang: str) -> str:
            rows = self.client.get(f"/v1/links/actions?lang={lang}").json()
            return next(r["label"] for r in rows if r["id"] == ident)

        self.assertEqual(label_for("fr"), "Cartes")
        self.assertNotEqual(label_for("de"), "Cartes")

    def test_public_cache_headers(self) -> None:
        r = self.client.get("/v1/links/actions?kind=map.transport")
        self.assertEqual(r.status_code, 200)
        self.assertIn("public", r.get("Cache-Control", ""))

    # ── /my/ namespace ──────────────────────────────────────────────

    def test_my_anonymous_rejected(self) -> None:
        r = self.client.get("/v1/my/links/actions")
        self.assertIn(r.status_code, (401, 403, 422))

    @override_settings(LOCAL_AUTH_ENABLED=True)
    def test_my_authenticated_gets_own_rows(self) -> None:
        client = Client(SERVER_NAME="localhost")
        client.force_login(self.user)
        r = client.get("/v1/my/links/actions")
        # The /my/ base enforces auth in dispatch (force_login sets an
        # authenticated session user) — 200 with own rows only.
        self.assertEqual(r.status_code, 200)
        ids = [row["id"] for row in r.json()]
        self.assertIn(self.user_action.link.identifier, ids)
        self.assertNotIn(self.public.link.identifier, ids)

    # ── Render ──────────────────────────────────────────────────────

    def test_render_substitution(self) -> None:
        ident = self.public.link.identifier
        r = self.client.get(f"/v1/links/actions/{ident}?name=Bern&lat=46.9&lon=7.4")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("Bern", body["url"])

    def test_render_unknown_404(self) -> None:
        r = self.client.get("/v1/links/actions/nonexistent?x=1")
        self.assertEqual(r.status_code, 404)

    def test_render_user_owned_404_for_others(self) -> None:
        ident = self.user_action.link.identifier
        r = self.client.get(f"/v1/links/actions/{ident}?name=x")
        self.assertEqual(r.status_code, 404)

    # ── Render built-ins: {lang} / {date} ──────────────────────────

    def test_render_lang_substitution(self) -> None:
        from datetime import timedelta

        from django.utils import timezone

        link, _ = ExternalLink.objects.get_or_create(
            url="https://www.sbb.ch/{lang}?stops={from}~{to}&day={date}&moment=dep",
            defaults={"label": "SBB", "run_health_check": False},
        )
        link.save(skip_health_check=True)
        ExternalAction.objects.create(link=link, user=None)
        r = self.client.get(
            f"/v1/links/actions/{link.identifier}?lang=fr&from=Bern&to=Kandersteg"
        )
        self.assertEqual(r.status_code, 200)
        url = r.json()["url"]
        self.assertIn("sbb.ch/fr?", url)
        self.assertIn("stops=Bern~Kandersteg", url)
        self.assertIn("moment=dep", url)
        tomorrow = (timezone.now() + timedelta(days=1)).date().isoformat()
        self.assertIn(f"day={tomorrow}", url)

    def test_render_selected_date_wins(self) -> None:
        link, _ = ExternalLink.objects.get_or_create(
            url="https://example.com/{date}",
            defaults={"label": "Dated", "run_health_check": False},
        )
        link.save(skip_health_check=True)
        ExternalAction.objects.create(link=link, user=None)
        r = self.client.get(f"/v1/links/actions/{link.identifier}?date=2026-12-24")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["url"], "https://example.com/2026-12-24")

    def test_render_invalid_date_rejected(self) -> None:
        link, _ = ExternalLink.objects.get_or_create(
            url="https://example.com/{date}",
            defaults={"label": "Dated", "run_health_check": False},
        )
        link.save(skip_health_check=True)
        ExternalAction.objects.create(link=link, user=None)
        r = self.client.get(f"/v1/links/actions/{link.identifier}?date=tomorrow")
        self.assertEqual(r.status_code, 400)

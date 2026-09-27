"""Tests for the meta image widget's external (raw) fallback.

Pinned external images have no local file — the widget must preview the raw
source URL, mark the serving mode, and offer the one-click "Download raw"
localization (spec: external-image-pinning, admin wiring).
"""

import pytest

from server.apps.meta_image_field.widgets import MetaImageWidget

RAW = "https://upload.wikimedia.org/wikipedia/commons/thumb/Test_1920.jpg"


def _render(widget: MetaImageWidget) -> str:
    return widget.render("image", None)


def test_raw_fallback_preview_and_download_button():
    widget = MetaImageWidget()
    widget.raw_url = RAW
    html = _render(widget)
    assert f'src="{RAW}"' in html
    assert 'id="image-preview"' in html
    assert "mfu-badge-external" in html  # "Served externally" hint
    assert "mfu-download-raw" in html
    assert f'data-raw-url="{RAW}"' in html
    assert "data-endpoint=" in html  # same-origin download proxy
    assert "mfu-rawlink" in html  # readonly clickable raw URL
    assert f'href="{RAW}"' in html
    assert "mfu-progress" in html  # progress bar markup


def test_no_raw_url_no_download_button():
    widget = MetaImageWidget()
    html = _render(widget)
    # The button always renders; without a raw source (and no typed URL) the
    # JS hides it — nothing to download.
    assert 'data-raw-url=""' in html
    assert "mfu-badge-none" in html  # "No image yet" hint
    assert 'id="image-preview"' not in html


def test_local_file_hint():
    class _FakeFieldFile:
        url = "/media/images/x.jpg"
        name = "images/x.jpg"
        width = 100
        height = 50

    widget = MetaImageWidget()
    widget.raw_url = RAW  # raw present but local file wins
    html = widget.render("image", _FakeFieldFile())
    assert 'src="/media/images/x.jpg"' in html
    assert "mfu-badge-local" in html  # "Stored locally" hint
    assert 'src="%s"' % RAW not in html


def test_widget_context_default_has_no_raw_url():
    widget = MetaImageWidget()
    context = widget.get_context("image", None, {})
    assert context["widget"]["raw_url"] is None


@pytest.mark.django_db
class TestImageAdminRawWiring:
    def test_pin_is_editable_without_local_file(
        self, seed_data, admin_client, settings
    ):
        """blank=True: a pinned image (no file) must pass admin form validation."""
        # The dev/test lane runs with the debug toolbar middleware, whose
        # templates cannot resolve their URLs inside the test client.
        from django.conf import settings as dj_settings

        settings.MIDDLEWARE = tuple(
            m for m in dj_settings.MIDDLEWARE if "debug_toolbar" not in m
        )
        from server.apps.images.models import Image, License

        license_obj, _ = License.objects.get_or_create(
            slug="cc-by-sa-4-0", defaults={"no_publication": False}
        )
        image = Image.objects.create(
            source_ident="wikicommons:File:WidgetTest.jpg",
            source_url_raw=RAW,
            license=license_obj,
        )
        response = admin_client.get(f"/admin/images/image/{image.id}/change/")
        assert response.status_code == 200
        assert RAW.encode() in response.content  # raw fallback wired


@pytest.mark.django_db
class TestDownloadRawEndpoint:
    """Same-origin proxy for the Download raw button (SSRF-guarded)."""

    def _setup_admin(self, settings):
        from django.conf import settings as dj_settings

        settings.MIDDLEWARE = tuple(
            m for m in dj_settings.MIDDLEWARE if "debug_toolbar" not in m
        )

    def test_private_url_rejected(self, admin_client, settings):
        from django.urls import reverse

        self._setup_admin(settings)
        for url in ("http://127.0.0.1/x.jpg", "http://192.168.1.1/x.jpg"):
            response = admin_client.get(
                reverse("admin:images_image_download_raw"), {"url": url}
            )
            assert response.status_code == 400, url

    def test_missing_url_rejected(self, admin_client, settings):
        from django.urls import reverse

        self._setup_admin(settings)
        response = admin_client.get(reverse("admin:images_image_download_raw"))
        assert response.status_code == 400

    def test_known_url_streams_content(self, admin_client, settings):
        from unittest.mock import MagicMock, patch

        from django.urls import reverse

        from server.apps.images.models import Image, License

        self._setup_admin(settings)
        license_obj, _ = License.objects.get_or_create(
            slug="cc-by-sa-4-0", defaults={"no_publication": False}
        )
        Image.objects.create(
            source_ident="wikicommons:File:DownloadTest.jpg",
            source_url_raw=RAW,
            license=license_obj,
        )
        fake = MagicMock()
        fake.raw.read.return_value = b"fake-image-bytes"
        fake.headers = {"Content-Type": "image/jpeg"}
        with patch("requests.get", return_value=fake):
            response = admin_client.get(
                reverse("admin:images_image_download_raw"), {"url": RAW}
            )
        assert response.status_code == 200
        assert response.content == b"fake-image-bytes"
        assert response["Content-Type"] == "image/jpeg"

    def test_anonymous_denied(self, client, settings):
        from django.urls import reverse

        self._setup_admin(settings)
        response = client.get(reverse("admin:images_image_download_raw"), {"url": RAW})
        assert response.status_code in (301, 302)  # redirect to admin login


@pytest.mark.django_db
class TestQuickActions:
    """Changelog quick buttons: review status, download raw, bulk actions."""

    def _no_toolbar(self, settings):
        from django.conf import settings as dj_settings

        settings.MIDDLEWARE = tuple(
            m for m in dj_settings.MIDDLEWARE if "debug_toolbar" not in m
        )

    def _pin(self):
        from server.apps.images.models import Image, License

        license_obj, _ = License.objects.get_or_create(
            slug="cc-by-sa-4-0", defaults={"no_publication": False}
        )
        return Image.objects.create(
            source_ident="wikicommons:File:QuickTest.jpg",
            source_url="https://commons.wikimedia.org/wiki/File:QuickTest.jpg",
            source_url_raw=RAW,
            license=license_obj,
            review_status=Image.ReviewStatusChoices.pending,
        )

    def test_set_review(self, admin_client, settings):
        from django.urls import reverse

        from server.apps.images.models import Image

        self._no_toolbar(settings)
        pin = self._pin()
        response = admin_client.get(
            reverse("admin:images_image_set_review", args=[pin.pk, "approved"])
        )
        assert response.status_code == 302
        pin.refresh_from_db()
        assert pin.review_status == Image.ReviewStatusChoices.approved

    def test_set_review_invalid_status(self, admin_client, settings):
        from django.urls import reverse

        self._no_toolbar(settings)
        pin = self._pin()
        response = admin_client.get(
            reverse("admin:images_image_set_review", args=[pin.pk, "bogus"])
        )
        assert response.status_code == 302
        pin.refresh_from_db()
        assert pin.review_status == "pending"  # unchanged

    def test_download_raw_row(self, admin_client, settings):
        from unittest.mock import MagicMock, patch

        from django.urls import reverse

        self._no_toolbar(settings)
        pin = self._pin()
        fake = MagicMock()
        fake.raw.read.return_value = b"fake-image-bytes"
        fake.headers = {"Content-Type": "image/jpeg"}
        with patch("requests.get", return_value=fake):
            response = admin_client.get(
                reverse("admin:images_image_download_raw_row", args=[pin.pk])
            )
        assert response.status_code == 302
        pin.refresh_from_db()
        assert bool(pin.image) is True
        assert pin.image.name.startswith("images/")
        assert "%C3%" not in pin.image.name  # sanitized ASCII name

    def test_bulk_download_action(self, admin_client, settings):
        from unittest.mock import MagicMock, patch

        from django.urls import reverse

        self._no_toolbar(settings)
        pin = self._pin()
        fake = MagicMock()
        fake.raw.read.return_value = b"fake-image-bytes"
        fake.headers = {"Content-Type": "image/jpeg"}
        with patch("requests.get", return_value=fake):
            response = admin_client.post(
                reverse("admin:images_image_changelist"),
                {
                    "action": "download_raw_selected_images",
                    "_selected_action": [str(pin.pk)],
                },
            )
        assert response.status_code == 302
        pin.refresh_from_db()
        assert bool(pin.image) is True


@pytest.mark.django_db
class TestQuickActionsAjax:
    """AJAX mode: JSON instead of redirects, for in-place row updates."""

    def _no_toolbar(self, settings):
        from django.conf import settings as dj_settings

        settings.MIDDLEWARE = tuple(
            m for m in dj_settings.MIDDLEWARE if "debug_toolbar" not in m
        )

    def _pin(self):
        from server.apps.images.models import Image, License

        license_obj, _ = License.objects.get_or_create(
            slug="cc-by-sa-4-0", defaults={"no_publication": False}
        )
        return Image.objects.create(
            source_ident="wikicommons:File:AjaxTest.jpg",
            source_url="https://commons.wikimedia.org/wiki/File:AjaxTest.jpg",
            source_url_raw=RAW,
            license=license_obj,
            review_status=Image.ReviewStatusChoices.pending,
        )

    def test_set_review_ajax_returns_json(self, admin_client, settings):
        from django.urls import reverse

        self._no_toolbar(settings)
        pin = self._pin()
        response = admin_client.get(
            reverse("admin:images_image_set_review", args=[pin.pk, "approved"]),
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "review_status": "approved"}
        pin.refresh_from_db()
        assert pin.review_status == "approved"

    def test_download_ajax_returns_json(self, admin_client, settings):
        from unittest.mock import MagicMock, patch

        from django.urls import reverse

        self._no_toolbar(settings)
        pin = self._pin()
        fake = MagicMock()
        fake.raw.read.return_value = b"fake-image-bytes"
        fake.headers = {"Content-Type": "image/jpeg"}
        with patch("requests.get", return_value=fake):
            response = admin_client.get(
                reverse("admin:images_image_download_raw_row", args=[pin.pk]),
                headers={"X-Requested-With": "XMLHttpRequest"},
            )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok" and body["local"] is True
        pin.refresh_from_db()
        assert bool(pin.image) is True

    def test_download_ajax_error_json(self, admin_client, settings):
        from unittest.mock import patch

        from django.urls import reverse

        self._no_toolbar(settings)
        pin = self._pin()
        with patch("requests.get", side_effect=RuntimeError("boom")):
            response = admin_client.get(
                reverse("admin:images_image_download_raw_row", args=[pin.pk]),
                headers={"X-Requested-With": "XMLHttpRequest"},
            )
        assert response.status_code == 502
        assert response.json()["status"] == "error"

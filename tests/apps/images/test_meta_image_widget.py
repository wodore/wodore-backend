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


def test_no_raw_url_no_download_button():
    widget = MetaImageWidget()
    html = _render(widget)
    assert "mfu-download-raw" not in html
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

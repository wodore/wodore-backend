"""Tests for image transformation logic (transfomer.py)."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

import server.core.utils as core_utils
from server.apps.images import transfomer
from server.apps.symbols import transfomer as symbols_transfomer
from server.core.utils import get_redirect_url


def _unique_url() -> str:
    """URL unique per run: `persistent` is a shared database cache whose
    entries survive `--reuse-db` across sessions, and cache keys are
    URL-derived."""
    return f"https://commons.wikimedia.example/{uuid4().hex}"


@pytest.mark.django_db
def test_redirect_result_cached_with_single_head_request(monkeypatch):
    """The final URL is cached; a repeated call performs no new HEAD."""
    url = _unique_url()
    final = f"https://upload.example/{uuid4().hex}"
    calls = []

    def fake_head(request_url, **kwargs):
        calls.append((request_url, kwargs))
        return SimpleNamespace(url=final)

    monkeypatch.setattr(core_utils.requests, "head", fake_head)

    assert get_redirect_url(url) == final
    assert get_redirect_url(url) == final
    assert len(calls) == 1  # second call served from the Django cache
    request_url, kwargs = calls[0]
    assert request_url == url
    assert kwargs["allow_redirects"] is True


@pytest.mark.django_db
def test_redirect_failure_not_cached_and_propagates(monkeypatch):
    """A failing HEAD propagates uncached; the next call retries."""
    url = _unique_url()
    attempts = []

    def flaky_head(request_url, **kwargs):
        attempts.append(request_url)
        if len(attempts) == 1:
            raise ConnectionError("boom")
        return SimpleNamespace(url="https://upload.example/recovered")

    monkeypatch.setattr(core_utils.requests, "head", flaky_head)

    with pytest.raises(ConnectionError):
        get_redirect_url(url)
    # not cached: the retry performs a new HEAD and succeeds
    assert get_redirect_url(url) == "https://upload.example/recovered"
    assert len(attempts) == 2


def test_redirect_helper_shared_between_media_transformers():
    """One implementation and cache namespace for images and symbols."""
    assert symbols_transfomer.get_redirect_url is transfomer.get_redirect_url

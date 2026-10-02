"""Shared test helpers for the dmr-based API."""

from django.test import Client

__test__ = False


class PrefixedClient(Client):
    """Django test client with a URL prefix (former ninja TestClient(router)).

    The ninja ``TestClient(router)`` allowed router-relative URLs like
    ``/hut/{slug}``. Endpoints are now mounted in the real URLconf, so
    tests use the full-stack Django client with the router's prefix.
    """

    def __init__(self, prefix: str = "", **kwargs):
        super().__init__(**kwargs)
        self.prefix = prefix

    def _prefixed(self, url: str) -> str:
        if url.startswith("http") or url.startswith(self.prefix):
            return url
        return self._prefix_url(url)

    def _prefix_url(self, url):
        return f"{self.prefix}{url}"

    def get(self, path, data=None, **kwargs):
        return super().get(self._prefixed(path), data, **kwargs)

    def post(self, path, data=None, **kwargs):
        return super().post(self._prefixed(path), data, **kwargs)

    def put(self, path, data=None, **kwargs):
        return super().put(self._prefixed(path), data, **kwargs)

    def delete(self, path, data=None, **kwargs):
        return super().delete(self._prefixed(path), data, **kwargs)

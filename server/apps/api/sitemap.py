"""XML sitemap generation for the public frontend (wodore.com).

Served under ``/v1`` — the frontend nginx proxies ``wodore.com/sitemap*.xml``
here (see wodore-frontend-quasar ``docker/nginx-default.conf``) — so all
``<loc>`` entries point at the frontend, while generation stays next to
the data on the API host.

Structure (sitemap index + paginated children, per sitemaps.org):

* ``/v1/sitemap.xml``           — index (static + one child per hut page)
* ``/v1/sitemap-static.xml``    — canonical entry pages (map, data policy)
* ``/v1/sitemap-huts-{n}.xml``  — ``SITEMAP_PAGE_SIZE`` public huts each

Scale: Google caps a single sitemap at 50k URLs / 50 MB. With 5k URLs per
page every response stays ~1 MB even at 10k+ huts, and each child is
cached independently. When places/POIs get public pages later, add a
``/v1/sitemap-places-{n}.xml`` route and register it in ``sitemap_index``
— no changes to the existing children needed.
"""

from __future__ import annotations

from xml.sax.saxutils import escape

from django.conf import settings
from django.core.cache import cache

from server.apps.huts.models import Hut

# URLs per child sitemap (see module docstring for the scale rationale).
SITEMAP_PAGE_SIZE = 5_000

# Child sitemaps change only when huts change, and crawlers re-fetch
# sitemaps at most daily — 48 h is plenty (hut data changes infrequently).
# The index additionally encodes the hut count (it decides how many
# children exist), so it refreshes faster to pick up new pages promptly.
SITEMAP_TTL = 60 * 60 * 48
SITEMAP_INDEX_TTL = 60 * 60


def frontend_url(path: str = "") -> str:
    """Absolute URL for a frontend path, based on ``FRONTEND_DOMAIN``."""
    base = settings.FRONTEND_DOMAIN.rstrip("/")
    return f"{base}/{path.lstrip('/')}"


def _url(loc: str, lastmod=None) -> str:
    lastmod_xml = f"<lastmod>{lastmod:%Y-%m-%d}</lastmod>" if lastmod else ""
    return f"<url><loc>{escape(loc)}</loc>{lastmod_xml}</url>"


def _urlset(entries: list[str]) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{''.join(entries)}"
        "</urlset>"
    )


def _public_huts_queryset():
    # Mirrors the public API surface: only huts the frontend can show.
    return Hut.objects.filter(is_active=True, is_public=True)


def sitemap_page_count() -> int:
    """Number of hut child sitemaps (cached with the index TTL)."""
    count = cache.get_or_set(
        "sitemap:huts:count",
        lambda: _public_huts_queryset().count(),
        SITEMAP_INDEX_TTL,
    )
    return max(1, -(-int(count) // SITEMAP_PAGE_SIZE))


def sitemap_index() -> str:
    """Sitemap index: static pages + all hut child sitemaps."""

    def build() -> str:
        children = [frontend_url("sitemap-static.xml")]
        children += [
            frontend_url(f"sitemap-huts-{page}.xml")
            for page in range(sitemap_page_count())
        ]
        entries = "".join(
            f"<sitemap><loc>{escape(c)}</loc></sitemap>" for c in children
        )
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            f"{entries}"
            "</sitemapindex>"
        )

    return cache.get_or_set("sitemap:index", build, SITEMAP_INDEX_TTL)


def sitemap_static() -> str:
    """Canonical frontend entry pages (no per-hut content here)."""

    def build() -> str:
        entries = [
            _url(frontend_url()),
            _url(frontend_url("data-policy")),
        ]
        return _urlset(entries)

    return cache.get_or_set("sitemap:static", build, SITEMAP_INDEX_TTL)


def sitemap_huts(page: int = 0) -> str | None:
    """One page of hut URLs, ordered by pk for stable pagination.

    Returns ``None`` for out-of-range pages (caller answers 404).
    """

    def build() -> str | None:
        huts = list(
            _public_huts_queryset()
            .order_by("pk")
            .values_list("slug", "modified")[
                page * SITEMAP_PAGE_SIZE : (page + 1) * SITEMAP_PAGE_SIZE
            ]
        )
        if not huts:
            return None
        return _urlset(
            [_url(frontend_url(f"hut/{slug}"), modified) for slug, modified in huts]
        )

    return cache.get_or_set(f"sitemap:huts:{page}", build, SITEMAP_TTL)

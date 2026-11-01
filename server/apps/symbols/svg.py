"""SVG sanitization for Martin sprite compatibility.

Martin 1.16 parses each sprite SVG with a strict XML parser and rejects
the file with ``NoRootNode`` unless every element sits in the *default*
SVG namespace — no ``ns0:``-style prefixes, an lxml serialization
artifact of the icon-generation step — and the root ``<svg>`` declares
``xmlns="http://www.w3.org/2000/svg"``. Staging had to patch both shapes
by hand on the Martin PVC; :func:`sanitize_svg` removes the need by
fixing the bytes at every hop that persists them
(``category_sync_assets`` writing Symbol files, ``martin_sync`` writing
sprite SVGs), so regenerating sprites never resurrects malformed files.

Text-level on purpose: clean SVGs pass through byte-identical (the
content-hashed symbol storage deduplicates on bytes, so byte-stability
matters) and the small, flat, single-namespace sprite SVGs need no full
re-serialization.
"""

from __future__ import annotations

import re

#: The XML namespace every SVG must declare as its default namespace.
SVG_NAMESPACE = "http://www.w3.org/2000/svg"

#: ``xmlns:<prefix>="…"`` declarations (double or single quoted).
_NS_DECL_RE = re.compile(r'xmlns:([A-Za-z_][\w.-]*)\s*=\s*(["\'])([^"\']*)\2')

#: The first root ``<svg …>`` start tag (quote-aware, so a ``>`` inside
#: an attribute value cannot truncate the match).
_ROOT_SVG_RE = re.compile(r"""<svg\b(?:[^>"']|"[^"]*"|'[^']*')*>""")


def sanitize_svg(content: bytes) -> bytes:
    """Return ``content`` with Martin-incompatible namespace quirks fixed.

    * prefixes bound to the SVG namespace (``ns0``, ``svg``, …) are
      stripped from element tags, their declaration promoted to the
      default namespace (or dropped when one already exists);
    * a root ``<svg>`` without a default ``xmlns`` declaration gets one.

    Idempotent and byte-stable: already-clean SVGs — and undecodable or
    rootless bytes — are returned unchanged.
    """
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return content

    svg_prefixes = {
        prefix
        for prefix, _quote, uri in _NS_DECL_RE.findall(text)
        if uri == SVG_NAMESPACE
    }
    for prefix in sorted(svg_prefixes):
        text = _rewrite_prefix(text, prefix)

    root = _ROOT_SVG_RE.search(text)
    if root is not None and "xmlns=" not in root.group(0):
        tag = root.group(0).replace("<svg", f'<svg xmlns="{SVG_NAMESPACE}"', 1)
        text = text[: root.start()] + tag + text[root.end() :]

    return text.encode("utf-8")


def _rewrite_prefix(text: str, prefix: str) -> str:
    """Bind one SVG-namespace ``prefix`` to the default namespace instead."""
    escaped = re.escape(prefix)
    text = re.sub(rf"<{escaped}:", "<", text)
    text = re.sub(rf"</{escaped}:", "</", text)

    root = _ROOT_SVG_RE.search(text)
    if root is None:
        return text
    if "xmlns=" not in root.group(0):
        # promote the prefixed declaration to the default namespace
        return re.sub(
            rf'xmlns:{escaped}(\s*=\s*)(["\']){re.escape(SVG_NAMESPACE)}\2',
            rf"xmlns\1\2{SVG_NAMESPACE}\2",
            text,
        )
    # a default declaration already exists — drop the redundant prefixed one
    return re.sub(
        rf'\s+xmlns:{escaped}\s*=\s*(["\']){re.escape(SVG_NAMESPACE)}\1',
        "",
        text,
    )

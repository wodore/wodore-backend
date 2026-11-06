"""``sanitize_svg``: Martin-compatible XML namespaces for sprite SVGs.

Staging incident (2026-11): Martin 1.16 rejected sprite SVGs whose
elements carried ``ns0:`` prefixes (lxml serialization artifact of the
icon-generation step) or whose root lacked the default ``xmlns``
declaration. These tests pin the sanitizer that keeps those files
parseable at every pipeline hop (``category_sync_assets`` → database,
``martin_sync`` → Martin PVC).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from server.apps.symbols.svg import SVG_NAMESPACE, sanitize_svg

SVG_NS = "{http://www.w3.org/2000/svg}"

DIRTY_NS0 = (
    b'<svg xmlns:ns0="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
    b'width="48" height="48"><ns0:path d="M0 0h24v24H0z"/></svg>'
)
DIRTY_NO_XMLNS = b'<svg viewBox="0 0 24 24"><path d="M0 0h24v24H0z"/></svg>'
CLEAN = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    f'<svg xmlns="{SVG_NAMESPACE}" viewBox="0 0 24 24">'
    '<path d="M0 0h24v24H0z"/></svg>'
).encode()


@pytest.mark.parametrize(
    ("dirty",),
    [(DIRTY_NS0,), (DIRTY_NO_XMLNS,)],
    ids=["ns0-prefix", "missing-xmlns"],
)
def test_sanitized_svg_parses_as_default_namespace_svg(dirty: bytes) -> None:
    """Both observed malformed shapes become XML Martin can parse: the
    default SVG namespace declared on the root, no element prefixes."""
    clean = sanitize_svg(dirty)

    assert b"ns0" not in clean
    root = ET.fromstring(clean)
    assert root.tag == f"{SVG_NS}svg"
    assert root[0].tag == f"{SVG_NS}path"


def test_ns0_prefix_is_stripped_and_declaration_promoted() -> None:
    clean = sanitize_svg(DIRTY_NS0)

    assert clean.startswith(
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"'
    )
    assert b"ns0" not in clean
    assert b"<ns0:" not in clean
    assert b"<path" in clean


def test_closing_tags_lose_the_prefix() -> None:
    dirty = (
        b'<svg xmlns:ns0="http://www.w3.org/2000/svg">'
        b'<ns0:g><ns0:path d="M0 0"/></ns0:g></svg>'
    )

    clean = sanitize_svg(dirty)

    assert b"</ns0:g>" not in clean
    assert b"</g>" in clean
    assert b"<g>" in clean


def test_inkscape_style_svg_prefix_alias_is_handled() -> None:
    dirty = (
        b'<svg:svg xmlns:svg="http://www.w3.org/2000/svg">'
        b'<svg:path d="M0 0"/></svg:svg>'
    )

    clean = sanitize_svg(dirty)

    assert b"svg:" not in clean
    assert b'xmlns="http://www.w3.org/2000/svg"' in clean
    assert ET.fromstring(clean).tag == f"{SVG_NS}svg"


def test_single_quoted_declarations_are_handled() -> None:
    dirty = b"<svg xmlns:ns0='http://www.w3.org/2000/svg'><ns0:path d=\"M0 0\"/></svg>"

    clean = sanitize_svg(dirty)

    assert b"ns0" not in clean
    # the declaration keeps its original quote style
    assert b"xmlns='http://www.w3.org/2000/svg'" in clean
    assert ET.fromstring(clean).tag == f"{SVG_NS}svg"


def test_redundant_prefix_declaration_is_dropped() -> None:
    dirty = (
        b'<svg xmlns="http://www.w3.org/2000/svg" '
        b'xmlns:ns0="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        b'<ns0:path d="M0 0"/></svg>'
    )

    clean = sanitize_svg(dirty)

    assert clean.count(b"xmlns=") == 1
    assert b"ns0" not in clean


def test_clean_svg_passes_through_unchanged() -> None:
    """Byte-stable for clean input — the content-hashed symbol storage
    deduplicates on bytes, so clean files must not be rewritten."""
    assert sanitize_svg(CLEAN) == CLEAN


def test_sanitization_is_idempotent() -> None:
    for dirty in (DIRTY_NS0, DIRTY_NO_XMLNS):
        once = sanitize_svg(dirty)
        assert sanitize_svg(once) == once


def test_non_svg_namespace_declarations_are_kept() -> None:
    xlink = b"http://www.w3.org/1999/xlink"
    clean_with_xlink = (
        f'<svg xmlns="{SVG_NAMESPACE}" xmlns:xlink="{xlink.decode()}">'
        '<path d="M0 0"/><use xlink:href="#p"/></svg>'
    ).encode()

    assert sanitize_svg(clean_with_xlink) == clean_with_xlink


def test_undecodable_bytes_pass_through() -> None:
    """Binary garbage is not our problem to fix — return it verbatim
    rather than crash the sync."""
    junk = b"\xff\xfe\x00<svg"

    assert sanitize_svg(junk) == junk


def test_rootless_content_passes_through() -> None:
    not_svg = b"<!DOCTYPE html><html></html>"

    assert sanitize_svg(not_svg) == not_svg

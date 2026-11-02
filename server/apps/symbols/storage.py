"""Content-addressed storage for symbol SVGs — moved to core.

The implementation lives in :mod:`server.core.storage` (shared by every
app writing mutable media). This module re-exports it because migration
``symbols.0015`` references ``server.apps.symbols.storage.ContentHashedStorage``
in its serialized field storage — the import path must stay stable.
New code should import from :mod:`server.core.storage` directly.
"""

from __future__ import annotations

import typing as t

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import connection

from server.apps.symbols.svg import sanitize_svg
from server.core.storage import (  # noqa: F401
    ContentHashedStorage,
    canonicalize_field_storage,
    hashed_name,
)

#: Module-level instance for ``FileField(storage=...)`` — importable and
#: deconstructible so migrations reference it by path.
hashed_symbol_storage = ContentHashedStorage()


def canonicalize_symbol_storage(
    symbol_model: t.Any, *, dry_run: bool = False
) -> dict[str, int]:
    """Backward-compatible wrapper (migration ``symbols.0016``)."""
    return canonicalize_field_storage(symbol_model, "svg_file", dry_run=dry_run)


def sanitize_symbol_storage(
    symbol_model: t.Any, *, dry_run: bool = False
) -> dict[str, int]:
    """Sanitize the stored SVG bytes of every symbol row (migration 0017).

    Heals files whose bytes predate the sanitize-on-write hops: lxml
    ``ns0:`` prefixes or a missing root ``xmlns`` are invisible to
    lenient consumers (HTML-inline parsing, ``fetch`` + innerHTML) but
    break strict ones — a browser refuses to decode such an SVG inside
    an ``<img>`` (``naturalWidth`` 0: the broken hut-detail type icon —
    every ``color__*`` variant was affected) and Martin's sprite parser
    rejects them (``NoRootNode``).

    Rows whose bytes change are re-saved under the new content hash
    (immutable URLs: a URL never changes content), and superseded files
    are deleted once no row references them (``0016`` semantics).
    Idempotent — clean files are byte-identical after ``sanitize_svg``
    and skipped. ``dry_run`` only counts. Raw SQL on purpose: model
    managers can build querysets historical migration models cannot
    resolve (see :func:`server.core.storage.canonicalize_field_storage`).
    """
    stats: dict[str, int] = {
        "sanitized": 0,
        "skipped": 0,
        "missing": 0,
        "deleted": 0,
    }
    field = symbol_model._meta.get_field("svg_file")
    table = symbol_model._meta.db_table
    column = field.column
    pk_column = symbol_model._meta.pk.column
    old_names: list[str] = []

    with connection.cursor() as cursor:
        cursor.execute(
            f'SELECT "{pk_column}", "{column}" FROM "{table}" '
            f'WHERE "{column}" IS NOT NULL AND "{column}" != %s',
            [""],
        )
        rows = cursor.fetchall()
    for pk, stored_name in rows:
        try:
            with default_storage.open(stored_name) as stored:
                content = stored.read()
        except (FileNotFoundError, OSError):
            stats["missing"] += 1
            continue
        clean = sanitize_svg(content)
        if clean == content:
            stats["skipped"] += 1
            continue
        if dry_run:
            stats["sanitized"] += 1
            continue
        saved_as = field.storage.save(stored_name, ContentFile(clean, name=stored_name))
        with connection.cursor() as cursor:
            cursor.execute(
                f'UPDATE "{table}" SET "{column}" = %s WHERE "{pk_column}" = %s',
                [saved_as, pk],
            )
        old_names.append(stored_name)
        stats["sanitized"] += 1

    if not dry_run:
        for old_name in old_names:
            with connection.cursor() as cursor:
                cursor.execute(
                    f'SELECT COUNT(*) FROM "{table}" WHERE "{column}" = %s',
                    [old_name],
                )
                (count,) = cursor.fetchone()
            if not count and default_storage.exists(old_name):
                default_storage.delete(old_name)
                stats["deleted"] += 1
    return stats

"""Content-addressed storage for media files.

Media is served with long immutable cache headers, so a filename must
map to exactly one content version — a deterministic name whose bytes
can change (import scripts re-writing files in place) leaves browsers
on stale bytes for the cache lifetime.

Central helpers (used by every app that writes mutable media):

* :class:`ContentHashedStorage` — delegating ``Storage`` that derives
  stored names from the content hash (sha256 suffix). Identical content
  keeps one canonical name (deduplicated); changed content lands on a
  fresh URL. Delegates everything else to the configured default
  storage (FileSystemStorage on the media PVC, S3 when enabled).
* :func:`save_content_hashed` — one-call helper for command scripts
  that write via ``default_storage`` directly.
* :func:`canonicalize_field_storage` — one-time migration helper that
  renames a model field's existing files onto their canonical names.

``server.apps.symbols.storage`` re-exports these (migration 0015
references that import path); new fields should import from here.
"""

from __future__ import annotations

import hashlib
import os
import re
from typing import Any

from django.core.files.base import ContentFile
from django.core.files.storage import Storage, default_storage

#: Length of the content-hash suffix appended to the file stem.
HASH_LEN = 10

#: An existing content-hash suffix (stripped before re-hashing so
#: re-saving an already-hashed file stays canonical).
_HASH_SUFFIX_RE = re.compile(r"_[0-9a-f]{10}$")


def hashed_name(name: str, content: Any) -> str:
    """Canonical content-addressed path for ``name`` + file content."""
    digest = hashlib.sha256()
    try:
        for chunk in content.chunks():
            digest.update(chunk)
    except AttributeError:  # plain file-like without .chunks()
        digest.update(content.read())
    try:
        content.seek(0)
    except (AttributeError, OSError):
        pass  # unwound streams just can't rewind — the caller owns it
    directory, base = os.path.split(name)
    stem, ext = os.path.splitext(base)
    stem = _HASH_SUFFIX_RE.sub("", stem)
    hashed = f"{stem}_{digest.hexdigest()[:HASH_LEN]}{ext}"
    return os.path.join(directory, hashed) if directory else hashed


class ContentHashedStorage(Storage):
    """Delegating storage that saves files under content-hashed names."""

    def __init__(self, inner: Storage | None = None):
        # Lazy default: resolve default_storage per call so settings
        # changes (test storage overrides, S3 flip) always apply.
        self._explicit_inner = inner

    @property
    def _inner(self) -> Storage:
        return self._explicit_inner if self._explicit_inner else default_storage

    # ── the actual point of this class ────────────────────────────────
    def save(self, name: str | None, content: Any, max_length: Any = None) -> str:
        if name is None:
            # No name to derive a hash from — plain delegation.
            return self._inner.save(name, content, max_length)
        target = hashed_name(name, content)
        if self._inner.exists(target):
            # Same content already stored — reuse the canonical name
            # instead of letting the backend append a collision suffix.
            return target
        return self._inner.save(target, content, max_length)

    # ── everything else delegates to the configured default storage ──
    def exists(self, name: str) -> bool:
        return self._inner.exists(name)

    def delete(self, name: str) -> None:
        self._inner.delete(name)

    def url(self, name: str | None) -> str:
        return self._inner.url(name)

    def size(self, name: str) -> int:
        return self._inner.size(name)

    def listdir(self, path: str) -> tuple[list[str], list[str]]:
        return self._inner.listdir(path)

    def get_available_name(self, name: str, max_length: Any = None) -> str:
        return self._inner.get_available_name(name, max_length)

    def path(self, name: str) -> str:
        return self._inner.path(name)

    def open(self, name: str, mode: str = "rb") -> Any:
        return self._inner.open(name, mode)

    def deconstruct(self) -> tuple[str, list[Any], dict[str, Any]]:
        """Path follows the importing module — stable per app."""
        path = f"{self.__class__.__module__}.{self.__class__.__qualname__}"
        return (path, [], {})


def save_content_hashed(name: str, content: bytes) -> str:
    """Store ``content`` under its canonical content-hashed name.

    One-call helper for command scripts that write through
    ``default_storage`` directly; returns the stored name.
    """
    file = ContentFile(content)
    canonical = hashed_name(name, file)
    if not default_storage.exists(canonical):
        default_storage.save(canonical, file)
    return canonical


def canonicalize_field_storage(
    model: Any, field_name: str, *, dry_run: bool = False
) -> dict[str, int]:
    """Rename a model field's existing files to content-hashed names.

    One pass over every row with a stored file: files already on their
    canonical name are skipped; others are re-saved under the canonical
    name (deduplicated by content), the row is updated to the new name,
    and old files are deleted once no row references them. Idempotent;
    returns ``{"renamed": n, "skipped": m, "deleted": k}``.
    """
    stats = {"renamed": 0, "skipped": 0, "deleted": 0}
    field = model._meta.get_field(field_name)
    table = model._meta.db_table
    column = field.column
    pk_column = model._meta.pk.column
    old_names: list[str] = []
    # Raw SQL on purpose: model managers (e.g. the i18n manager) can
    # build querysets that historical migration models cannot resolve.
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute(
            f'SELECT "{pk_column}", "{column}" FROM "{table}" '
            f'WHERE "{column}" IS NOT NULL AND "{column}" != %s',
            [""],
        )
        rows = cursor.fetchall()
    for pk, old_name in rows:
        try:
            with default_storage.open(old_name) as stored:
                content = stored.read()
        except (FileNotFoundError, OSError):
            stats["skipped"] += 1
            continue
        canonical = hashed_name(old_name, ContentFile(content))
        if canonical == old_name:
            stats["skipped"] += 1
            continue
        if dry_run:
            stats["renamed"] += 1
            continue
        saved_as = field.storage.save(old_name, ContentFile(content))
        with connection.cursor() as cursor:
            cursor.execute(
                f'UPDATE "{table}" SET "{column}" = %s WHERE "{pk_column}" = %s',
                [saved_as, pk],
            )
        old_names.append(old_name)
        stats["renamed"] += 1
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


#: Shared instance for ``FileField(storage=...)`` across apps.
hashed_media_storage = ContentHashedStorage()

"""Content-addressed storage for symbol SVGs.

Media files are served with long immutable cache headers, so a filename
must map to exactly one content version — a deterministic name whose
bytes can change (the icon-import overwrite dance: collision suffix,
then cleanup frees the base name again) makes browsers serve stale
SVGs for the cache lifetime. This storage derives the stored name from
the content hash: identical content keeps one canonical name
(deduplicated), changed content always lands on a fresh URL.

Used by ``Symbol.svg_file``; everything except ``save`` delegates to
the configured default storage (FileSystemStorage on the media PVC,
S3 when enabled), so it works under both backends.
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
    def save(  # pyright: ignore[reportIncompatibleVariableOverride]
        self, name: str | None, content: Any, max_length: Any = None
    ) -> str:
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
    def exists(self, name: str) -> bool:  # pyright: ignore[reportIncompatibleVariableOverride]
        return self._inner.exists(name)

    def delete(self, name: str) -> None:
        self._inner.delete(name)

    def url(self, name: str | None) -> str:  # pyright: ignore[reportIncompatibleVariableOverride]
        return self._inner.url(name)

    def size(self, name: str) -> int:
        return self._inner.size(name)

    def listdir(self, path: str) -> tuple[list[str], list[str]]:
        return self._inner.listdir(path)

    def get_available_name(  # pyright: ignore[reportIncompatibleVariableOverride]
        self, name: str, max_length: Any = None
    ) -> str:
        return self._inner.get_available_name(name, max_length)

    def path(self, name: str) -> str:
        return self._inner.path(name)

    def open(self, name: str, mode: str = "rb") -> Any:
        return self._inner.open(name, mode)

    def deconstruct(self) -> tuple[str, list[Any], dict[str, Any]]:
        """Keep FileField migrations stable across settings."""
        return ("server.apps.symbols.storage.ContentHashedStorage", [], {})


#: Module-level instance for ``FileField(storage=...)`` — importable and
#: deconstructible so migrations reference it by path.
hashed_symbol_storage = ContentHashedStorage()


def canonicalize_symbol_storage(
    symbol_model: Any, *, dry_run: bool = False
) -> dict[str, int]:
    """Rename existing symbol files to their content-hashed names.

    One pass over every ``Symbol`` row with a stored file: files already
    on their canonical name are skipped; others are re-saved under the
    canonical name (deduplicated by content), the row is updated to the
    new name, and old files are deleted once no row references them.
    Idempotent; returns ``{"renamed": n, "skipped": m, "deleted": k}``.
    """
    stats = {"renamed": 0, "skipped": 0, "deleted": 0}
    old_names: list[str] = []
    for symbol in symbol_model.objects.exclude(svg_file="").exclude(
        svg_file__isnull=True
    ):
        old_name = symbol.svg_file.name
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
        saved_as = hashed_symbol_storage.save(old_name, ContentFile(content))
        symbol_model.objects.filter(pk=symbol.pk).update(svg_file=saved_as)
        old_names.append(old_name)
        stats["renamed"] += 1
    for old_name in old_names:
        still_referenced = symbol_model.objects.filter(svg_file=old_name).exists()
        if not still_referenced and default_storage.exists(old_name):
            default_storage.delete(old_name)
            stats["deleted"] += 1
    return stats

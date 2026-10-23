"""Content-addressed storage for symbol SVGs — moved to core.

The implementation lives in :mod:`server.core.storage` (shared by every
app writing mutable media). This module re-exports it because migration
``symbols.0015`` references ``server.apps.symbols.storage.ContentHashedStorage``
in its serialized field storage — the import path must stay stable.
New code should import from :mod:`server.core.storage` directly.
"""

from __future__ import annotations

from typing import Any

from server.core.storage import (  # noqa: F401
    ContentHashedStorage,
    canonicalize_field_storage,
    hashed_name,
)

#: Module-level instance for ``FileField(storage=...)`` — importable and
#: deconstructible so migrations reference it by path.
hashed_symbol_storage = ContentHashedStorage()


def canonicalize_symbol_storage(
    symbol_model: Any, *, dry_run: bool = False
) -> dict[str, int]:
    """Backward-compatible wrapper (migration ``symbols.0016``)."""
    return canonicalize_field_storage(symbol_model, "svg_file", dry_run=dry_run)

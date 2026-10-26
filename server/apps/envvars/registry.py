"""Registry snapshot, precedence and invalidation.

Precedence per name (strict allowlist — ``envvars.EnvVar`` rows):

====================  ==============================================
no row                unresolvable; the process environment is never
                     consulted for unregistered names
row inactive          forbidden — does not resolve at all (operator
                     kill switch, even when the env var is set)
row value set         the stored value wins
row value empty +     fall back to the process environment ∪ Django
``env_fallback``      settings; absent → unresolvable
row value empty, no   explicitly empty: resolves to ``""`` (the
``env_fallback``      operator pinned the empty value on purpose)
====================  ==============================================

Row snapshots are cached (short TTL + signal invalidation on every
registry edit). The environment fallback resolves per call, so
per-process env changes apply immediately — only the row set is cached.

Downstream semantics: ``resolve``/``resolve_many`` return anything
resolvable (``""`` included); ``usable`` additionally rejects empty
results unless the emptiness was pinned — basemaps availability gating
(:func:`basemaps.resolution.missing_env_names`) treats those as missing.
"""

from __future__ import annotations

import os

from django.conf import settings
from django.core.cache import cache

#: Cache key of the row snapshot (tests and signals invalidate it).
CACHE_KEY = "envvars:registry"

#: Freshness bound only — signals delete the key on every edit.
SNAPSHOT_TTL = 10

#: (value, is_active, env_fallback) — the resolvable row payload.
Row = tuple[str, bool, bool]


def rows() -> dict[str, Row]:
    """All registry rows as ``{name: (value, is_active, env_fallback)}``."""
    snapshot: dict[str, Row] | None = cache.get(CACHE_KEY)
    if snapshot is None:
        from .models import EnvVar

        snapshot = {
            row.name: (row.value or "", row.is_active, row.env_fallback)
            for row in EnvVar.objects.all()
        }
        cache.set(CACHE_KEY, snapshot, SNAPSHOT_TTL)
    return snapshot


def _setting_or_env(name: str) -> str | None:
    """Boot-config fallback: the Django setting when defined, else env.

    The setting is decouple's boot-time snapshot of the process
    environment plus ``.env`` files and wins on purpose: infisical-
    injected values land on the setting at boot anyway, and
    ``override_settings`` in tests must not lose to a stray shell
    export of the same name. Names that are not Django settings
    (operational API keys) resolve from the live process environment.
    """
    if hasattr(settings, name):
        return str(getattr(settings, name))
    if name in os.environ:
        return os.environ[name]
    return None


def resolve(name: str, snapshot: dict[str, Row] | None = None) -> str | None:
    """Resolve one name per the precedence matrix.

    Returns ``None`` when the name does not resolve (unregistered,
    inactive, or empty-with-fallback and no setting/environment value);
    ``""`` when an explicitly pinned empty value resolves. The fallback
    reads the Django setting first, then the process environment (see
    ``_setting_or_env``).
    """
    snap = rows() if snapshot is None else snapshot
    row = snap.get(name)
    if row is None:
        return None
    value, active, env_fallback = row
    if not active:
        return None
    if value:
        return value
    if not env_fallback:
        return ""  # pinned empty
    return _setting_or_env(name)


def resolve_many(
    names: set[str], snapshot: dict[str, Row] | None = None
) -> dict[str, str]:
    """Resolve the given names once — resolvable entries only."""
    snap = rows() if snapshot is None else snapshot
    return {
        name: resolved
        for name in names
        if (resolved := resolve(name, snap)) is not None
    }


def usable(name: str, snapshot: dict[str, Row] | None = None) -> bool:
    """True when the name resolves to a value layers may serve.

    A resolved empty string only counts when the emptiness was pinned
    (``env_fallback=False``); an empty environment value is treated as
    missing — blank keys in URLs are accidents, not intent.
    """
    snap = rows() if snapshot is None else snapshot
    row = snap.get(name)
    if row is None:
        return False
    value, active, env_fallback = row
    if not active:
        return False
    if value:
        return True
    if not env_fallback:
        return True  # pinned empty
    return bool(resolve(name, snap))


def _rows_or_empty() -> dict[str, Row]:
    """Registry rows, or an empty snapshot when the DB is unreachable.

    ``resolve_setting`` must stay usable wherever the plain Django
    setting was (SimpleTestCase tests, early boot, degraded cache):
    a blocked or unavailable database degrades to "registry off" —
    the Django setting serves — instead of raising.
    """
    try:
        return rows()
    except Exception:  # any DB/cache failure degrades to "registry off"
        return {}


def resolve_setting(name: str, default: str = "") -> str:
    """Runtime value for a Django-settings-backed name (URL origins).

    Lets operators override deploy-time URL settings —
    ``MARTIN_TILE_URL``, ``IMAGOR_URL``, ``BACKEND_DOMAIN`` — from the
    admin without a redeploy. Precedence:

    * active row with a stored value → the stored value
    * active row, empty, ``env_fallback=False`` → pinned empty (``""``)
    * everything else (no row, inactive row, empty + fallback) → the
      Django setting itself, else ``default``

    Unlike :func:`resolve` the process environment is not consulted
    directly: decouple loads ``.env``/infisical values onto the
    *setting* at boot, and reading ``os.environ`` here would make
    ``override_settings`` in tests (and decouple-loaded config) lose
    against a stray shell export of the same name.
    """
    snap = _rows_or_empty()
    row = snap.get(name)
    if row is not None:
        value, active, env_fallback = row
        if active:
            if value:
                return value
            if not env_fallback:
                return ""  # pinned empty
    setting_value: object = getattr(settings, name, default)
    return default if setting_value is None else str(setting_value)


def invalidate(*_: object, **_kwargs: object) -> None:
    """Drop the row snapshot (signal receiver on every registry edit)."""
    cache.delete(CACHE_KEY)


def connect() -> None:
    """Hook registry edits to snapshot invalidation."""
    from django.db.models.signals import post_delete, post_save

    from .models import EnvVar

    post_save.connect(invalidate, sender=EnvVar, dispatch_uid="envvars.invalidate")
    post_delete.connect(invalidate, sender=EnvVar, dispatch_uid="envvars.invalidate")

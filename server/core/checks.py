"""Startup validation: the vendored cache backport must not outlive 6.1.

``server.core.cache_backends.SampledCullDatabaseCache`` backports Django
6.2's ``CULL_PROBABILITY`` cull gate (upstream ticket #32785) onto the
Django 6.1 line this project pins — see the module and Sentry issue
155299999 for context. Once the project runs Django >= 6.2 the backport is
superseded by the built-in backend and must be removed.

This check makes that removal enforced instead of remembered: as soon as
``django.VERSION`` reaches (6, 2), any CACHES alias still wired to the
vendored backend fails startup (and CI — management commands run system
checks) with removal instructions. Dependabot's weekly uv updates can bump
``Django==6.*`` to 6.2 as soon as it releases; that PR then cannot go
green until the backport is gone.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import django
from django.conf import settings
from django.core import checks

E001 = "core.E001"

#: First Django version whose DatabaseCache ships the sampled cull check
#: (OPTIONS["CULL_PROBABILITY"], ticket #32785).
UPSTREAM_FIXED_IN = (6, 2)

VENDORED_BACKEND_PREFIX = "server.core.cache_backends"


def _validate(
    caches_config: Mapping[str, Mapping[str, Any]],
    version: Sequence[Any],
) -> list[checks.CheckMessage]:
    """Pure core of the check — directly testable with a simulated version."""
    if tuple(version[:2]) < UPSTREAM_FIXED_IN:
        return []

    offending = sorted(
        alias
        for alias, cfg in caches_config.items()
        if str(cfg.get("BACKEND", "")).startswith(VENDORED_BACKEND_PREFIX)
    )
    if not offending:
        return []

    return [
        checks.Error(
            f"Caches alias(es) {', '.join(repr(a) for a in offending)} still "
            f"use the vendored {VENDORED_BACKEND_PREFIX}.SampledCullDatabaseCache, "
            f"but Django {UPSTREAM_FIXED_IN[0]}.{UPSTREAM_FIXED_IN[1]} ships the "
            f"sampled cull check natively (OPTIONS['CULL_PROBABILITY'], "
            f"ticket #32785) — the backport is superseded.",
            hint="Switch the BACKEND of the affected alias(es) to "
            "django.core.cache.backends.db.DatabaseCache (OPTIONS stay "
            f"identical), then delete {VENDORED_BACKEND_PREFIX}.py and its "
            "tests, and the core.E001 check itself.",
            id=E001,
        )
    ]


@checks.register(checks.Tags.compatibility)
def check_vendored_cache_backend_removed_on_django_62(
    app_configs: Any = None, **kwargs: Any
) -> list[checks.CheckMessage]:
    """Fail startup on Django >= 6.2 while the backport is still wired."""
    return _validate(settings.CACHES, django.VERSION)

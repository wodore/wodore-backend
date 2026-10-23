"""Admin-managed environment variable registry (strict allowlist).

``{{env:NAME}}`` tokens in basemap styles and external ``style_url``s
resolve through this registry — the process environment is never
consulted for unregistered names, so admin-editable style documents
cannot read arbitrary server configuration.

Precedence per name (see ``registry.py`` for the full matrix):

* no row                     → unresolvable
* ``is_active=False``        → forbidden (kill switch; env ignored)
* ``value`` set              → stored value wins
* ``value`` empty, fallback  → process environment ∪ Django settings
* ``value`` empty, pinned    → explicitly empty (``""``)

Values are operational API keys that end up in URLs clients fetch —
they are public by nature and get no encryption at rest; obviously
secretive names are refused outright (``EnvVar.clean``).
"""

from __future__ import annotations

import re
from typing import Any

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from server.core.models import TimeStampedModel

#: Same charset as ``basemaps.validation.ENV_TOKEN_RE``.
NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")

#: Names that must never resolve — a value referenced by a public style
#: URL leaks to every client.
FORBIDDEN_NAMES = frozenset({"SECRET_KEY", "DATABASE_URL"})
#: Substrings marking a name as server-secret.
FORBIDDEN_PARTS = ("PASSWORD", "PRIVATE", "TOKEN", "SECRET")


class EnvVar(TimeStampedModel):
    """One admin-managed environment variable (allowlist entry)."""

    name = models.CharField(
        _("Name"),
        max_length=100,
        unique=True,
        db_index=True,
        help_text=_(
            "Variable name, UPPER_SNAKE_CASE, stored uppercase "
            "(e.g. WODORE_MAPTILER_API_KEY)"
        ),
    )
    value = models.TextField(
        _("Value"),
        blank=True,
        default="",
        help_text=_(
            "Stored value wins when set; empty falls back to the process "
            "environment unless pinned (see below)"
        ),
    )
    env_fallback = models.BooleanField(
        _("Env fallback"),
        default=True,
        help_text=_(
            "When the value is empty, fall back to the process environment "
            "(infisical). Unchecked: the empty value is intentional and "
            "overrides the environment"
        ),
    )
    is_active = models.BooleanField(
        _("Active"),
        default=True,
        db_index=True,
        help_text=_("Inactive entries never resolve — not even from the environment"),
    )
    description = models.CharField(
        _("Description"),
        blank=True,
        default="",
        max_length=255,
        help_text=_("What this variable is used for (admin hint)"),
    )

    class Meta:  # pyright: ignore[reportIncompatibleVariableOverride]
        verbose_name = _("Environment variable")
        verbose_name_plural = _("Environment variables")
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Normalize the name to uppercase — registry lookups are exact."""
        self.name = self.name.upper()
        super().save(*args, **kwargs)

    def clean(self) -> None:
        """Normalize case, then reject bad shapes and server-secret names."""
        self.name = (self.name or "").upper()
        if not NAME_RE.match(self.name):
            raise ValidationError(
                {"name": "Name must be UPPER_SNAKE_CASE ([A-Z][A-Z0-9_]*)"}
            )
        if self.name in FORBIDDEN_NAMES or any(
            part in self.name for part in FORBIDDEN_PARTS
        ):
            raise ValidationError(
                {
                    "name": (
                        "Refusing to register a server-secret name — style "
                        "documents are public; register operational API "
                        "keys only"
                    )
                }
            )

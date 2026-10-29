"""Category extra-attribute schemas.

OpenSpec ``geoplace-capacity-and-types-via-categories`` (revised
design): the JSON structure of ``GeoPlaceCategory.extra`` is described
by a JSON Schema (draft 2020-12) stored per category — seeded once by
data migration (accommodation parent: the ``capacity`` key), then
admin-manageable (``Organization.props_schema`` parity: code owns the
initial setup, admins evolve it).

Resolution: an association resolves its schema through its category —
the category's own schema first, else the parent's (exactly one
level, mirroring the ``mode``/``role`` classifier guards). Validation
runs on every write path (model ``clean()``, the import schema path,
the admin form) through the shared
``GeoPlaceCategory.validate_attributes``.

Guardrails (advisor review): the schema is checked against the JSON
Schema metaschema on save, ``additionalProperties: false`` is rejected
(the codebase invariant is *preserve unknown keys*), and a corrupt
stored schema fails OPEN at read time (loud log, no validation)
rather than bricking every write under the category — including the
admin page that would fix it.
"""

import logging
from typing import Any, override

from jsonschema import Draft202012Validator

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from server.core.models import TimeStampedModel

logger = logging.getLogger(__name__)

#: Compiled validators keyed by ``(schema pk, modified timestamp)`` —
#: editing a schema row invalidates its entry. Per-run cache, same
#: idiom as the importer's ``_operator_role``.
_validator_cache: dict[tuple[int, str], Draft202012Validator] = {}


class CategoryExtraSchema(TimeStampedModel):
    """A JSON Schema describing one category subtree's ``extra`` keys."""

    #: FK id attribute — plugin-less inference gap for string-ref
    #: OneToOne fields (pyrefly), same idiom as modeltrans ``_i18n``.
    category_id: int

    category = models.OneToOneField(
        "categories.Category",
        on_delete=models.RESTRICT,
        related_name="extra_schema",
        db_index=True,
        verbose_name=_("Category"),
        help_text=_("Category this schema applies to (children inherit it)"),
    )
    schema = models.JSONField(
        default=dict,
        verbose_name=_("Schema"),
        help_text=_(
            "JSON Schema (draft 2020-12) for this category's association "
            "extra attributes. Evolve additively: new optional keys are "
            "safe; tightening or renaming keys breaks existing rows on "
            "their next write. additionalProperties must stay permissive."
        ),
    )

    class Meta:
        verbose_name = _("Category Extra Schema")
        verbose_name_plural = _("Category Extra Schemas")
        ordering = ("category__identifier",)

    def __str__(self) -> str:
        return f"extra schema: {self.category.identifier if self.category_id else '?'}"  # type: ignore  # plugin-less inference gap

    @override
    def clean(self) -> None:
        super().clean()
        # Metaschema guard: an invalid schema never enters the DB —
        # the single most important guardrail (advisor finding).
        try:
            Draft202012Validator.check_schema(self.schema)
        except Exception as exc:  # jsonschema raises assorted types
            raise ValidationError(
                {"schema": _("Not a valid JSON Schema: %(error)s") % {"error": exc}}
            ) from exc
        # The codebase invariant is *preserve unknown keys* — a strict
        # schema would reject every row carrying preserved keys.
        if self.schema.get("additionalProperties") is False:
            raise ValidationError(
                {
                    "schema": _(
                        "additionalProperties: false is not allowed — "
                        "unknown keys are preserved by design."
                    )
                }
            )

    def compiled_validator(self) -> Draft202012Validator | None:
        """Compile (cached) or degrade to ``None`` on a corrupt schema."""
        if not self.pk or not self.schema:
            return None
        key = (self.pk, self.modified.isoformat() if self.modified else "")
        validator = _validator_cache.get(key)
        if validator is None:
            try:
                Draft202012Validator.check_schema(self.schema)
                validator = Draft202012Validator(self.schema)
            except Exception:  # degrade, don't brick writes
                logger.exception(
                    "Corrupt extra schema on category %s — failing open "
                    "(no validation until fixed in the admin)",
                    self.category_id,
                )
                return None
            if len(_validator_cache) > 128:  # bounded
                _validator_cache.clear()
            _validator_cache[key] = validator
        return validator


def resolve_extra_schema(category: Any) -> CategoryExtraSchema | None:
    """Resolve the schema for a category — own row first, else parent's.

    Exactly one level of fallback, mirroring the ``mode``/``role``
    classifier guards; a schema on a parent applies to all children.
    """
    if category is None or category.pk is None:
        return None
    schema = getattr(category, "extra_schema", None)
    if schema is not None:
        return schema
    parent = getattr(category, "parent", None)
    if parent is not None and parent.pk is not None:
        return getattr(parent, "extra_schema", None)
    return None


def validate_place_extra(categories: Any, extra: dict[str, Any]) -> None:
    """Validate ``GeoPlace.extra`` against the kind-root schema (task 2.6).

    Same resolution and guardrails as association extra: the kind
    root's own ``CategoryExtraSchema`` (explicit row) with no deeper
    fallback — no schema → free-form; corrupt → fail open, logged.
    """
    from ..kinds import kind_root_category

    root = kind_root_category(categories)
    if root is None:
        return
    schema_row = resolve_extra_schema(root)
    if schema_row is None:
        return
    validator = schema_row.compiled_validator()
    if validator is None:
        return
    error = next(validator.iter_errors(extra), None) if extra else None
    if error is not None:
        raise ValidationError(
            {
                "extra": _(
                    "Value does not match the place kind's extra schema: %(error)s"
                )
                % {"error": error.message}
            }
        )

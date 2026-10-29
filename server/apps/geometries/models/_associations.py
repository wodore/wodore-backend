from typing import Any, override

from computedfields.models import ComputedFieldsModel

from modeltrans.manager import MultilingualManager

from django.contrib.gis.db import models
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from server.apps.categories.models import Category
from server.apps.images.models import Image
from server.apps.organizations.models import Organization
from server.core.models import TimeStampedModel


class UpdatePolicy(models.TextChoices):
    """How a source may update records."""

    ALWAYS = "always", _("Always overwrite all fields")
    MERGE = "merge", _("Skip fields edited by wodore source")
    PROTECTED = "protected", _("Never overwrite")
    AUTO_PROTECT = "auto_protect", _("Merge until wodore.modified_date, then protected")


class DeletePolicy(models.TextChoices):
    """What happens when a source no longer includes a record."""

    DEACTIVATE = "deactivate", _("Set is_active=False")
    KEEP = "keep", _("Ignore deletion")
    DELETE = "delete", _("Hard delete")
    AUTO_KEEP = "auto_keep", _("Deactivate until wodore.modified_date, then keep")


class GeoPlaceImageAssociation(TimeStampedModel):
    # Mirror of HutImageAssociation's score bands: provider pins stay in
    # 0–89, curated content would live in 90–99 (geoplaces currently have no
    # uploads — kept for parity so pin_place_images can clamp uniformly).
    PROVIDER_SCORE_MAX = 89

    image = models.ForeignKey(
        Image, on_delete=models.CASCADE, db_index=True, related_name="geoplace_details"
    )
    geo_place = models.ForeignKey(
        "GeoPlace",
        on_delete=models.CASCADE,
        db_index=True,
        related_name="image_associations",
    )
    score = models.PositiveSmallIntegerField(
        blank=True,
        null=True,
        help_text=_(
            "Display score — higher is shown first; pinned external images stay in 0–89."
        ),
    )

    def __str__(self) -> str:
        return f"{self.geo_place} <> {self.image}"

    class Meta:
        verbose_name = _("Image and Geo Place Association")
        ordering = ("geo_place__name", "-score", "id")
        constraints = (
            models.UniqueConstraint(
                name="%(app_label)s_%(class)s_unique_relationships",
                fields=["image", "geo_place"],
            ),
        )


class GeoPlaceSourceAssociation(TimeStampedModel, ComputedFieldsModel):
    objects = MultilingualManager()

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="geoplace_sources",
        db_index=True,
    )
    geo_place = models.ForeignKey(
        "GeoPlace",
        on_delete=models.CASCADE,
        db_index=True,
        related_name="source_associations",
    )
    source_props = models.JSONField(
        help_text=_("Source properties."), blank=True, default=dict
    )
    source_id = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        default="",
        help_text="Source id",
        db_index=True,  # Add index for faster lookups in import_geoplaces
    )

    extra = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Extra"),
        help_text=_("Source-specific overflow data (JSON)"),
    )

    import_date = models.DateTimeField(auto_now_add=True)
    modified_date = models.DateTimeField(
        auto_now=False,
        null=True,
        blank=True,
        db_index=True,
        help_text=_("Last time this source updated the record"),
    )
    confidence = models.FloatField(
        default=1.0, help_text="Confidence in this source match (0-1)"
    )

    # Import policies
    update_policy = models.CharField(
        max_length=20,
        choices=UpdatePolicy.choices,
        default=UpdatePolicy.AUTO_PROTECT,
        verbose_name=_("Update Policy"),
        help_text=_("How this source may update the record"),
    )

    delete_policy = models.CharField(
        max_length=20,
        choices=DeletePolicy.choices,
        default=DeletePolicy.AUTO_KEEP,
        verbose_name=_("Delete Policy"),
        help_text=_("What happens when this source no longer includes the record"),
    )

    priority = models.PositiveSmallIntegerField(
        default=10,
        db_index=True,
        verbose_name=_("Priority"),
        help_text=_("Source precedence for field conflicts (lower number wins)"),
    )

    class Meta:
        verbose_name = _("Geo Place and Organization Association")
        indexes = [
            models.Index(fields=["priority"]),
        ]
        constraints = (
            # Unique constraint on organization + source_id prevents duplicate imports
            models.UniqueConstraint(
                name="%(app_label)s_%(class)s_unique_org_source",
                fields=["organization", "source_id"],
                condition=models.Q(source_id__isnull=False) & ~models.Q(source_id=""),
            ),
            models.UniqueConstraint(
                name="%(app_label)s_%(class)s_unique_relationships",
                fields=["organization", "geo_place"],
            ),
            models.CheckConstraint(
                name="%(app_label)s_%(class)s_update_policy_valid",
                condition=models.Q(
                    update_policy__in=["always", "merge", "protected", "auto_protect"]
                ),
            ),
            models.CheckConstraint(
                name="%(app_label)s_%(class)s_delete_policy_valid",
                condition=models.Q(
                    delete_policy__in=["deactivate", "keep", "delete", "auto_keep"]
                ),
            ),
        )

    def __str__(self) -> str:
        return f"{self.geo_place} <> {self.organization}"


class GeoPlaceExternalLink(models.Model):
    """
    Through-model connecting GeoPlaces to ExternalLinks.

    Allows the same ExternalLink to be associated with multiple GeoPlaces
    with different ordering.
    """

    geo_place = models.ForeignKey(
        "GeoPlace",
        on_delete=models.CASCADE,
        db_index=True,
        related_name="link_associations",
        verbose_name=_("Geo Place"),
    )

    external_link = models.ForeignKey(
        "external_links.ExternalLink",
        on_delete=models.CASCADE,
        db_index=True,
        related_name="place_associations",
        verbose_name=_("External Link"),
    )

    order = models.PositiveSmallIntegerField(
        default=0,
        db_index=True,
        verbose_name=_("Order"),
        help_text=_("Display order for this link"),
    )

    class Meta:
        verbose_name = _("Geo Place Link")
        verbose_name_plural = _("Geo Place Links")
        ordering = ["order", "id"]
        indexes = [
            models.Index(fields=["geo_place", "order"]),
            models.Index(fields=["external_link"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["geo_place", "external_link"],
                name="%(app_label)s_%(class)s_unique_place_link",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.geo_place.name_i18n} → {self.external_link.label_i18n}"


class GeoPlaceCategory(TimeStampedModel):
    """Through model for GeoPlace <-> Category with operation modes.

    OpenSpec ``geoplace-capacity-and-types-via-categories`` (revised
    design): an association pairs a category with an operation mode —
    the ``classifier`` references a ``mode.*`` child (today
    ``mode.standard`` / ``mode.reduced``). A hut imports as up to two
    associations (standard operation, reduced operation), each
    carrying its mode's typed attributes in ``extra`` (the
    accommodation schema: ``capacity``). ``extra`` is validated
    against the category subtree's ``CategoryExtraSchema`` (JSON
    Schema, admin-manageable); values the source does not publish are
    omitted (``None``-valued keys dropped, never stored as null),
    unknown keys are preserved.
    """

    geo_place = models.ForeignKey(
        "GeoPlace",
        on_delete=models.CASCADE,
        db_index=True,
        related_name="category_associations",
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.RESTRICT,
        db_index=True,
        related_name="geo_place_associations",
    )
    classifier = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_index=True,
        related_name="classifications",
        help_text=_("Operation mode for this association (a mode.* child category)"),
    )
    extra = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Extra"),
        help_text=_(
            "Per-association attributes — validated against the "
            "category's extra schema (JSON Schema)"
        ),
    )

    class Meta:
        db_table = "geometries_geoplace_category"
        verbose_name = _("Geo Place Category Association")
        verbose_name_plural = _("Geo Place Category Associations")
        ordering = ["geo_place", "category"]
        indexes = [
            models.Index(
                fields=["category", "geo_place"],
                name="gpc_cat_place_idx",
            ),
            models.Index(
                fields=["geo_place", "category"],
                name="gpc_place_cat_idx",
            ),
            models.Index(fields=["classifier"], name="gpc_classifier_idx"),
        ]
        constraints = [
            # One association per (place, category, mode) — the
            # two-association operating-mode model pairs a category
            # with mode.standard AND mode.reduced when open and closed
            # types coincide (e.g. unknown/unknown). NULL classifiers
            # are not distinct (PG15+ ``nulls_distinct``) so a NULL row
            # stays unique per category too.
            models.UniqueConstraint(
                fields=["geo_place", "category", "classifier"],
                nulls_distinct=False,
                name="geoplacecategory_unique_place_category_mode",
            ),
        ]

    def __str__(self) -> str:
        classifier_str = f" [{self.classifier.slug}]" if self.classifier else ""
        return (
            f"{self.geo_place.name_i18n} -> {self.category.identifier}{classifier_str}"
        )

    @override
    def clean(self) -> None:
        super().clean()
        self.validate_attributes(self.category, self.classifier, self.extra)

    @classmethod
    def validate_attributes(
        cls,
        category: "Category | None",
        classifier: "Category | None",
        extra: dict[str, Any],
    ) -> None:
        """Shared validation for every write path (D3).

        ``clean()`` (admin forms), the schema upsert and the wodore
        import all funnel through here — Django calls ``clean()`` on
        none of the latter two paths. The classifier must be a child
        of one of the **kind's allowed classifier subtrees**
        (``CategoryKindContract.allowed_classifiers`` — the DB
        contract on the kind's group, admin-editable; a missing
        contract allows none);
        ``extra`` is validated against the category subtree's
        ``CategoryExtraSchema`` (no schema → free-form; corrupt
        stored schema → fail open, logged).
        """
        from ..kinds import kind_contract_state

        if classifier is not None:
            parent = classifier.parent
            _contract, allowed = kind_contract_state(category)
            if parent is None or parent.slug not in allowed:
                raise ValidationError(
                    {
                        "classifier": _(
                            "Classifier must be a child of one of this "
                            "kind's allowed categories (allowed: %(allowed)s)."
                        )
                        % {"allowed": ", ".join(allowed) or _("none")}
                    }
                )
        cls.validate_extra(category, extra)

    @classmethod
    def validate_extra(cls, category: "Category | None", extra: dict[str, Any]) -> None:
        """Validate ``extra`` against the category's extra schema.

        No schema on the category subtree → free-form (forward-
        compatible); a corrupt stored schema fails open (loud log at
        compile time, no validation) — writes never brick.
        """
        from ._category_extra_schema import resolve_extra_schema

        schema_row = resolve_extra_schema(category)
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
                        "Value does not match the category's extra schema: %(error)s"
                    )
                    % {"error": error.message}
                }
            )

    @classmethod
    def normalize_extra(cls, extra: dict[str, Any] | None) -> dict[str, Any]:
        """Drop ``None``-valued keys (unknown keys preserved).

        A value the source does not publish is omitted, not stored
        as ``null`` — an empty dict means no published attributes.
        """
        if not extra:
            return {}
        return {key: value for key, value in extra.items() if value is not None}


class GeoPlaceParty(TimeStampedModel):
    """Role-classified association between a GeoPlace and a Party.

    Mirrors the ``classifier`` pattern of ``GeoPlaceCategory``: the
    ``role`` FK must reference a category under the ``role`` parent
    (validated in ``clean()`` and the schema write path), and multiple
    roles for the same place–party pair are separate rows — one role
    classifier per row.
    """

    geo_place = models.ForeignKey(
        "GeoPlace",
        on_delete=models.CASCADE,
        db_index=True,
        related_name="party_associations",
        verbose_name=_("Geo Place"),
    )
    party = models.ForeignKey(
        "parties.Party",
        on_delete=models.RESTRICT,
        db_index=True,
        related_name="geo_place_associations",
        verbose_name=_("Party"),
    )
    role = models.ForeignKey(
        Category,
        on_delete=models.RESTRICT,
        db_index=True,
        related_name="party_associations",
        verbose_name=_("Role"),
        help_text=_("Role this party plays for the place (role.* category)"),
    )
    order = models.PositiveSmallIntegerField(
        default=0,
        db_index=True,
        verbose_name=_("Order"),
        help_text=_("Display order among same-role associations"),
    )

    class Meta:
        verbose_name = _("Geo Place Party Association")
        verbose_name_plural = _("Geo Place Party Associations")
        ordering = ["geo_place", "role", "order", "id"]
        indexes = [
            models.Index(
                fields=["party", "geo_place"],
                name="gpp_party_place_idx",
            ),
            models.Index(
                fields=["geo_place", "role"],
                name="gpp_place_role_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["geo_place", "party", "role"],
                name="geoplaceparty_unique_place_party_role",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"{self.geo_place.name_i18n} → {self.party.name_i18n}"
            f" [{self.role.identifier}]"
        )

    @override
    def clean(self) -> None:
        super().clean()
        if self.role_id:
            parent = self.role.parent
            if parent is None or parent.slug != "role":
                raise ValidationError(
                    {
                        "role": _(
                            "Role must be a role.* category "
                            "(a child of the 'role' parent)."
                        )
                    }
                )

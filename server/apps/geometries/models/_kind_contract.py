"""Kind contract on a contract-group category (DB, admin-editable).

OpenSpec ``geoplace-category-tree``: the contract that used to live in
the ``PLACE_KINDS`` code registry is a DB row on the contract group
(the category one level above the kind — ``accommodation`` for
``accommodation.hut``), seeded from the registry by migration and then
admin-editable — ``CategoryExtraSchema`` parity: structure in git,
evolution in the admin. A missing row is the empty contract: no
classifiers, no operations, no seasonality.
"""

from __future__ import annotations

from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from server.core.models import TimeStampedModel


class CategoryKindContract(TimeStampedModel):
    """Which models apply to places under one contract group."""

    #: FK id attributes — plugin-less inference gap (pyrefly idiom).
    category_id: int

    category = models.OneToOneField(
        "categories.Category",
        on_delete=models.CASCADE,
        db_index=True,
        related_name="kind_contract",
        verbose_name=_("Contract group"),
        help_text=_(
            "The contract-group category (e.g. accommodation for "
            "accommodation.hut) this contract applies to"
        ),
    )
    allowed_classifiers = models.ManyToManyField(
        "categories.Category",
        blank=True,
        related_name="kind_contracts",
        limit_choices_to=Q(parent__isnull=True) & ~Q(slug="map"),
        verbose_name=_("Allowed classifiers"),
        help_text=_(
            "Classifier vocabulary roots (mode, role, …) permitted on "
            "associations under this group"
        ),
    )
    has_operations = models.BooleanField(
        default=False,
        verbose_name=_("Has operations"),
        help_text=_("Places under this group may carry operation rows"),
    )
    has_seasonality = models.BooleanField(
        default=False,
        verbose_name=_("Has seasonality"),
        help_text=_("Places under this group may carry seasonality rows"),
    )

    class Meta:
        verbose_name = _("Category Kind Contract")
        verbose_name_plural = _("Category Kind Contracts")
        ordering = ["category__slug"]

    def __str__(self) -> str:
        flags = []
        if self.has_operations:
            flags.append("ops")
        if self.has_seasonality:
            flags.append("season")
        suffix = f" ({', '.join(flags)})" if flags else ""
        return f"{self.category_id}{suffix}"

    @classmethod
    def allows_classifier(
        cls, contract_group_id: int, classifier_parent_id: int
    ) -> bool:
        """Whether the classifier's vocabulary root is allowed."""
        return cls.objects.filter(
            category_id=contract_group_id,
            allowed_classifiers=classifier_parent_id,
        ).exists()

    @classmethod
    def group_allows_operations(cls, contract_group_id: int) -> bool:
        """Whether the group's contract enables operation rows."""
        return cls.objects.filter(
            category_id=contract_group_id, has_operations=True
        ).exists()

    @classmethod
    def group_allows_seasonality(cls, contract_group_id: int) -> bool:
        """Whether the group's contract enables seasonality rows."""
        return cls.objects.filter(
            category_id=contract_group_id, has_seasonality=True
        ).exists()

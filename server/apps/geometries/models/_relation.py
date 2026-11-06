"""Semantic relation edges between places.

OpenSpec ``geoplace-kinds-operations-graph`` (tasks 3.1–3.3, adopted
from draft PR #154): one-direction edges typed by a ``relations/*``
category (``part_of``, ``near``, ``serves``, ``access_point``), stored
exactly once per triple — reverse queries swap the FK direction via
``outgoing_relations`` / ``incoming_relations``. ``confidence``
defaults to 1.0 (curated); auto-generated edges store < 1.0 and are
replaced idempotently on re-runs.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from server.core.models import TimeStampedModel

#: Auto-generated edges carry this confidence until curated.
GENERATED_CONFIDENCE = 0.8


class GeoPlaceRelation(TimeStampedModel):
    """One semantic edge between two places."""

    #: FK id attributes — plugin-less inference gap (pyrefly idiom).
    from_place_id: int
    to_place_id: int
    relation_id: int

    from_place = models.ForeignKey(
        "GeoPlace",
        on_delete=models.CASCADE,
        db_index=True,
        related_name="outgoing_relations",
        verbose_name=_("From place"),
    )
    to_place = models.ForeignKey(
        "GeoPlace",
        on_delete=models.CASCADE,
        db_index=True,
        related_name="incoming_relations",
        verbose_name=_("To place"),
    )
    relation = models.ForeignKey(
        "categories.Category",
        on_delete=models.RESTRICT,
        db_index=True,
        related_name="place_relations",
        limit_choices_to={"parent__slug": "relations"},
        verbose_name=_("Relation"),
        help_text=_("Edge type (relations.* category)"),
    )
    confidence = models.FloatField(
        default=1.0,
        help_text=_("1.0 = curated; < 1.0 = auto-generated, replaced on re-runs"),
    )
    extra = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Overflow data for this edge (JSON)"),
    )

    class Meta:
        verbose_name = _("Geo Place Relation")
        verbose_name_plural = _("Geo Place Relations")
        ordering = ["from_place", "relation__order", "to_place"]
        indexes = [
            models.Index(
                fields=["from_place", "relation"],
                name="gpr_from_relation_idx",
            ),
            models.Index(
                fields=["to_place", "relation"],
                name="gpr_to_relation_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["from_place", "to_place", "relation"],
                name="geoplacerelation_unique_triple",
            ),
            models.CheckConstraint(
                name="%(app_label)s_%(class)s_no_self_loops",
                condition=~models.Q(from_place=models.F("to_place")),
            ),
        ]

    def __str__(self) -> str:
        return f"{self.from_place_id} -[{self.relation_id}]-> {self.to_place_id}"

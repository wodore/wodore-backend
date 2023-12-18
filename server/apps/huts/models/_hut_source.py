from model_utils.models import TimeStampedModel

from django.contrib.gis.db import models
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _

from server.apps.organizations.models import Organization
from server.core.managers import BaseManager


class _ReviewStatusChoices(models.TextChoices):
    # waiting = 'waiting'
    new = "new", _("new")
    review = "review", _("review")
    done = "done", _("done")
    old = "old", _("old")
    failed = "failed", _("failed")
    reject = "reject", _("reject")


class HutSource(TimeStampedModel):
    """
    Source data for huts, e.g from SAC.
    """

    ReviewStatusChoices = _ReviewStatusChoices

    objects: BaseManager = BaseManager()

    source_id = models.CharField(
        blank=False, max_length=100, verbose_name=_("Source ID"), help_text=_("Original ID from source object.")
    )
    version = models.PositiveSmallIntegerField(default=0, verbose_name=_("Version"))
    name = models.CharField(blank=False, max_length=100, verbose_name=_("Name"), help_text=_("Name of the object"))
    organization = models.ForeignKey(Organization, on_delete=models.RESTRICT)
    location = models.PointField(blank=True, default=None, verbose_name=_("Location"))
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        verbose_name=_("Active"),
        help_text=_("If set to inactive no more updates are done from this source"),
    )
    is_current = models.BooleanField(default=True, db_index=True, verbose_name=_("Current Entry"))
    review_status = models.TextField(
        max_length=12,
        choices=ReviewStatusChoices.choices,
        default=ReviewStatusChoices.new,
        verbose_name=_("Review status"),
    )
    review_comment = models.CharField(blank=True, default="", verbose_name=_("Review comment"), max_length=2000)
    source_data = models.JSONField(
        verbose_name=_("Source data as JSON"), help_text=_("Data from the source model."), blank=True, default=dict
    )
    source_properties = models.JSONField(
        verbose_name=_("Source properties as JSON"),
        help_text=_("Additional properties from the source model."),
        blank=True,
        default=dict,
    )
    previous_object = models.ForeignKey(
        "self",
        blank=True,
        null=True,
        on_delete=models.RESTRICT,
        verbose_name=_("Previous Entry"),
        help_text=_("Id to the previous object."),
    )
    hut = models.ForeignKey("Hut", null=True, related_name="sources", on_delete=models.SET_NULL, verbose_name=_("Hut"))

    class Meta:
        verbose_name = "Hut Source"
        verbose_name_plural = "Hut Sources"
        ordering = (Lower("name"), "organization__order")
        constraints = (
            models.CheckConstraint(
                name="%(app_label)s_%(class)s_review_status_valid",
                check=models.Q(review_status__in=_ReviewStatusChoices.values),
            ),
        )

    def __str__(self) -> str:
        return f"{self.name} v{self.version} ({self.organization.name_i18n})"

from model_utils.models import TimeStampedModel

from django.contrib.gis.db import models
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _

from server.apps.organizations.models import Organization
from server.core.managers import BaseManager


class ReviewStatusChoices(models.TextChoices):
    # waiting = 'waiting'
    new = "new", _("new")
    review = "review", _("review")
    done = "done", _("done")
    old = "old", _("old")
    reject = "reject", _("reject")


class HutSource(TimeStampedModel):
    """
    Source data for huts, e.g from SAC.
    """

    objects: BaseManager = BaseManager()

    source_id = models.CharField(blank=False, max_length=100, help_text=_("Original id from source object."))
    version = models.PositiveSmallIntegerField(default=0)
    name = models.CharField(blank=False, max_length=100, help_text=_("Name of the object object."))
    organization = models.ForeignKey(Organization, on_delete=models.RESTRICT)
    point = models.PointField(blank=True, default=None)
    is_active = models.BooleanField(default=True, db_index=True)
    is_current = models.BooleanField(default=True, db_index=True)
    review_status = models.TextField(
        max_length=12, choices=ReviewStatusChoices.choices, default=ReviewStatusChoices.new
    )
    review_comment = models.CharField(blank=True, default="", max_length=2000)
    source_data = models.JSONField(help_text=_("Data from the source model."), blank=True, default=dict)
    previous_object = models.ForeignKey(
        "self", blank=True, null=True, on_delete=models.RESTRICT, help_text=_("Id to the previous object.")
    )
    hut = models.ForeignKey("Hut", null=True, related_name="sources", on_delete=models.SET_NULL)

    class Meta:
        verbose_name = "Hut Source"
        verbose_name_plural = "Hut Sources"
        ordering = (Lower("name"), "organization__order")

    def __str__(self) -> str:
        return f"{self.name} v{self.version} ({self.organization.name_i18n})"

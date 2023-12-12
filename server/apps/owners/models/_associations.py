from model_utils.models import TimeStampedModel

from django.contrib.gis.db import models
from django.utils.translation import gettext_lazy as _

from server.apps.contacts.models import Contact
from server.core.managers import BaseMutlilingualManager


class OwnerContactAssociation(TimeStampedModel):
    objects = BaseMutlilingualManager()

    contact = models.ForeignKey(
        Contact,
        on_delete=models.CASCADE,
        related_name="owner_details",
        verbose_name=_("Contact"),
    )
    owner = models.ForeignKey("Owner", on_delete=models.CASCADE, verbose_name=_("Owner"))
    order = models.PositiveSmallIntegerField(blank=True, null=True, db_index=True, verbose_name=_("Order"))

    def __str__(self) -> str:
        return f"{self.owner} <> {self.contact}"

    class Meta:
        verbose_name = _("Contacts to Owner")
        unique_together = (("contact", "owner"),)
        ordering = ("contact__function__priority", "order", "owner__name")

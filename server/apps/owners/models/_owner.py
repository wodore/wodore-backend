from model_utils.models import TimeStampedModel
from modeltrans.fields import TranslationField

from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _

from server.apps.contacts.models import Contact
from server.core.managers import BaseMutlilingualManager

from ._associations import OwnerContactAssociation


class Owner(TimeStampedModel):
    i18n = TranslationField(fields=("name", "note"))
    objects = BaseMutlilingualManager()

    slug = models.SlugField(unique=True, db_index=True)
    name = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name=_("Name"),
        help_text=_("For example 'SAC Bern', 'Naturschutzverein Hergiswil', ..."),
    )
    url = models.URLField(blank=True, default="", max_length=200, verbose_name=_("URL"))
    note = models.TextField(blank=True, default="", max_length=500, verbose_name=_("Note"))
    contacts = models.ManyToManyField(
        Contact, blank=True, through=OwnerContactAssociation, related_name="owner", verbose_name=_("Contacts")
    )

    class Meta:
        verbose_name = _("Owner")
        indexes = (GinIndex(fields=["i18n"]),)
        ordering = (Lower("name_i18n"),)

    def __str__(self) -> str:
        return self.name_i18n

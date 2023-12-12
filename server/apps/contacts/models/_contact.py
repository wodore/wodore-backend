from model_utils.models import TimeStampedModel
from modeltrans.fields import TranslationField

from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _

from server.core.managers import BaseMutlilingualManager

from ._contact_function import ContactFunction


class Contact(TimeStampedModel):
    objects = BaseMutlilingualManager()
    i18n = TranslationField(fields=("note",))

    name = models.CharField(blank=True, default="", max_length=70, verbose_name=_("Name"))
    email = models.EmailField(blank=True, default="", max_length=70, verbose_name=_("E-Mail"))
    phone = models.CharField(blank=True, default="", max_length=30, verbose_name=_("Phone"))
    mobile = models.CharField(blank=True, default="", max_length=30, verbose_name=_("Mobile"))
    # function = models.CharField(blank=True, max_length=50, help_text=_("Function (e.g. hut warden)"))  # maybe as enum?
    function = models.ForeignKey(ContactFunction, on_delete=models.RESTRICT, related_name="contacts")
    url = models.URLField(blank=True, default="", max_length=200, verbose_name=_("URL"))
    address = models.CharField(blank=True, default="", max_length=200, verbose_name=_("Address"))
    note = models.TextField(blank=True, null=True, max_length=500, verbose_name=_("Note"))
    is_active = models.BooleanField(
        default=True, db_index=True, verbose_name=_("Active"), help_text=_("Only shown to admin if not active")
    )
    is_public = models.BooleanField(
        default=False, db_index=True, verbose_name=_("Public"), help_text=_("Only shown to editors if not public")
    )

    class Meta:
        verbose_name = _("Contact")
        indexes = (GinIndex(fields=["i18n"]),)
        ordering = (Lower("name"),)

    def __str__(self) -> str:
        out = []
        if self.name:
            out.append(self.name)
        if self.email:
            out.append(f"<{self.email}>")
        return " ".join(out)

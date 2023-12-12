from djjmt.fields import TranslationJSONField

from model_utils.models import TimeStampedModel
from modeltrans.fields import TranslationField

from django.db import models
from django.utils.translation import gettext_lazy as _

from server.core.managers import BaseMutlilingualManager


class ContactFunction(models.Model):
    i18n = TranslationField(fields=("name",))
    objects = BaseMutlilingualManager()

    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=100, blank=True, null=True, help_text="Function name")
    icon = models.CharField(blank=True, max_length=70, help_text=_("Icon"))
    priority = models.PositiveSmallIntegerField(
        default=0, help_text=_("Priorty, used for ordering. Lower number has higher priority.")
    )

    def __str__(self) -> str:
        return self.name_i18n

    class Meta:
        verbose_name = _("Function")
        ordering = ("priority", "name_i18n")


class Contact(TimeStampedModel):
    i18n = TranslationField(fields=("note",))
    objects = BaseMutlilingualManager()

    name = models.CharField(blank=True, default="", max_length=70, help_text=_("Name"))
    email = models.EmailField(blank=True, default="", max_length=70, help_text=_("E-Mail"))
    phone = models.CharField(blank=True, default="", max_length=30, help_text=_("Phone"))
    mobile = models.CharField(blank=True, default="", max_length=30, help_text=_("Mobile"))
    # function = models.CharField(blank=True, max_length=50, help_text=_("Function (e.g. hut warden)"))  # maybe as enum?
    function = models.ForeignKey(ContactFunction, on_delete=models.RESTRICT)
    url = models.URLField(blank=True, default="", max_length=200, help_text=_("URL"))
    address = models.CharField(blank=True, default="", max_length=200, help_text=_("Address"))
    note = models.TextField(blank=True, null=True, max_length=500, help_text=_("Note"))
    is_active = models.BooleanField(default=True, db_index=True)
    is_public = models.BooleanField(default=False, db_index=True)

    class Meta:
        verbose_name = _("Contact")
        verbose_name_plural = _("Contacts")
        # ordering = ["order"]

    def __str__(self) -> str:
        out = []
        if self.name:
            out.append(self.name)
        if self.email:
            out.append(f"<{self.email}>")
        return " ".join(out)


class Owner(TimeStampedModel):
    i18n = TranslationField(fields=("name", "note"))
    objects = BaseMutlilingualManager()

    name = models.CharField(max_length=100, null=True, blank=True, help_text="Owner name (e.g. SAC Bern)")
    url = models.URLField(blank=True, default="", max_length=200, help_text=_("URL"))
    note = models.TextField(blank=True, default="", max_length=500, help_text=_("Note"))

    def __str__(self) -> str:
        return self.name_i18n

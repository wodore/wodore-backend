from model_utils.models import TimeStampedModel
from modeltrans.fields import TranslationField

from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.utils.translation import gettext_lazy as _

from server.core.managers import BaseMutlilingualManager


class ContactFunction(TimeStampedModel):
    """Function of a contact, e.g. warden ..."""

    i18n = TranslationField(fields=("name",))
    objects = BaseMutlilingualManager()

    slug = models.SlugField(unique=True, db_index=True)
    name = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name=_("Function"),
        help_text=_("For example 'warden', 'hut owner', 'cook', ..."),
    )
    symbol = models.ImageField(
        max_length=300,
        upload_to="contacts/function/symbol",
        default="contacts/function/symbol/default.png",
        verbose_name=_("Symbol"),
        help_text=_("Contact function symbol, should be square and good visible if small."),
    )
    priority = models.PositiveSmallIntegerField(
        default=0,
        help_text=_("Priorty, used for ordering. Lower number has higher priority."),
        verbose_name=_("Priority"),
        db_index=True,
    )

    # contacts -> access all contacts

    class Meta:
        verbose_name = _("Contact Function")
        ordering = ("priority", "name_i18n")
        indexes = (GinIndex(fields=["i18n"]),)

    def __str__(self) -> str:
        return self.name_i18n

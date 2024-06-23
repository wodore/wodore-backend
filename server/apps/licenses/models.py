from model_utils.models import TimeStampedModel
from modeltrans.fields import TranslationField
from functools import lru_cache

from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.utils.translation import gettext_lazy as _

from server.core.managers import BaseMutlilingualManager


class License(TimeStampedModel):
    i18n = TranslationField(fields=("name", "fullname", "description", "link"))
    objects = BaseMutlilingualManager()

    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=40, default="", blank=True, null=True, verbose_name=_("Shortname"))
    fullname = models.CharField(max_length=100, default="", blank=True, null=True, verbose_name=_("Fullname"))
    description = models.TextField(default="", blank=True, null=True, help_text=_("Description"))
    link = models.URLField(blank=True, max_length=300, null=True)

    is_active = models.BooleanField(default=True)
    order = models.PositiveSmallIntegerField(unique=False, default=0, verbose_name=_("Order"))
    # license permissions
    attribution_required = models.BooleanField(default=True)
    no_commercial = models.BooleanField(default=True)
    no_modifying = models.BooleanField(default=True)
    share_alike = models.BooleanField(default=True)
    no_publication = models.BooleanField(default=False)
    # icon = models.ImageField(_("icon"), upload_to="licenses/icons/")

    class Meta:
        verbose_name = _("License")
        ordering = ("order", "name_i18n")
        indexes = (GinIndex(fields=["i18n"]),)

    def __str__(self) -> str:
        return f"{self.name_i18n} - {self.fullname_i18n}"

    @classmethod
    @lru_cache(50)
    def get_by_slug(cls, slug: str) -> "License":
        return cls.objects.get(slug=slug)

    @classmethod
    def get_fields_all(cls) -> list[str]:
        return [
            "slug",
            "name",
            "fullname",
            "description",
            "link",
            "latest",
            "is_active",
            "order",
        ]

    @classmethod
    def get_fields_in(cls):
        return list(set(cls.get_fields_all()) - {"created", "modified", "id", "order"})

    @classmethod
    def get_fields_update(cls):
        return list(set(cls.get_fields_all()) - {"created", "modified"})

    @classmethod
    def get_fields_out(cls):
        return cls.get_fields_all()

    @classmethod
    def get_fields_exclude(cls):
        return ["created", "modified"]

    @classmethod
    def get_next_order_number(cls):
        highest_order = License.objects.all().order_by("-order").values("order").first()
        if highest_order is None:
            return 0
        return highest_order.get("order", 0) + 10

    def save(self, *args, **kwargs):
        if self.order == 0 or self.order is None:
            self.order = License.get_next_order_number()
        super().save(*args, **kwargs)

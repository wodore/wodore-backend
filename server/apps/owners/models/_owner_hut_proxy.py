from django.utils.translation import gettext_lazy as _

from server.apps.huts.models import Hut


class OwnerHutProxy(Hut):
    class Meta:
        proxy = True
        ordering = ("owner__name_i18n",)
        verbose_name = _("Hut Association")

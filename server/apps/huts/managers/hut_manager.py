from modeltrans.manager import MultilingualManager

from server.core.managers import BaseManager


class HutManager(MultilingualManager, BaseManager):
    ...


# HutManager = _HutManager.from_queryset(BaseQuerySet)

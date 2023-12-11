from server.core.managers import BaseManager

from modeltrans.manager import MultilingualManager


class HutManager(MultilingualManager, BaseManager):
    ...


# HutManager = _HutManager.from_queryset(BaseQuerySet)

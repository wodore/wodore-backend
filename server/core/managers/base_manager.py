from django.db import models
from modeltrans.manager import MultilingualManager


class BaseQuerySet(models.QuerySet):
    def drop(self, limit: int | None = None, offset: int | None = 0, **kwargs) -> tuple[int, dict[str, int]]:
        """Drops data from database table, same as delete but let you five a limit and offset argument."""
        offset = offset or 0
        qs = self
        entries = qs.all().count()
        if limit is not None:
            limit_with_offset = limit + offset
            if limit_with_offset > entries:
                limit_with_offset = entries
            if offset > entries:
                offset = entries
            pks = qs.all()[offset:limit_with_offset].values_list("pk", flat=True)
        else:
            pks = qs.all().values_list("pk", flat=True)
        return qs.filter(pk__in=pks).delete(**kwargs)


class BaseManager(models.Manager):
    def get_queryset(self):
        return BaseQuerySet(self.model, using=self._db)  # Important!

    def drop(self, limit: int | None = None, offset: int | None = 0, **kwargs) -> tuple[int, dict[str, int]]:
        """Drops data from database table, same as delete but let you five a limit and offset argument."""
        return self.get_queryset().drop(limit=limit, offset=offset, **kwargs)


class BaseMutlilingualManager(MultilingualManager, BaseManager):
    pass

from typing import Any, TypeVar, override

from modeltrans.manager import MultilingualManager

from django.db import models

_M = TypeVar("_M", bound=models.Model, default=Any)


class BaseQuerySet(models.QuerySet[_M, _M]):
    def drop(
        self, limit: int | None = None, offset: int | None = 0, **kwargs: Any
    ) -> tuple[int, dict[str, int]]:
        """Drops data from database table, same as delete but let you five a limit and offset argument."""
        offset = offset or 0
        qs = self
        entries = qs.all().count()
        if limit is not None:
            limit_with_offset = limit + offset
            limit_with_offset = min(limit_with_offset, entries)
            offset = min(offset, entries)
            pks = qs.all()[offset:limit_with_offset].values_list("pk", flat=True)
        else:
            pks = qs.all().values_list("pk", flat=True)
        qs = qs.filter(pk__in=pks)
        return qs.delete(**kwargs)


class BaseManager(models.Manager[_M]):
    @override
    def get_queryset(self) -> BaseQuerySet[_M]:
        return BaseQuerySet(self.model, using=self._db)  # Important!

    def drop(
        self, limit: int | None = None, offset: int | None = 0, **kwargs: Any
    ) -> tuple[int, dict[str, int]]:
        """Drops data from database table, same as delete but let you five a limit and offset argument."""
        return self.get_queryset().drop(limit=limit, offset=offset, **kwargs)


class BaseMutlilingualManager(MultilingualManager, BaseManager):
    """Multilingual manager (modeltrans) mixed with `BaseManager` helpers.

    `get_queryset` is declared explicitly: the MRO chains
    `MultilingualManager.get_queryset` → `BaseManager.get_queryset`
    (modeltrans patches the resulting `BaseQuerySet` class into a
    `MultilingualQuerySet`, keeping `drop()` etc.). The explicit
    declaration reconciles both base signatures for type checkers.
    """

    def get_queryset(self) -> models.QuerySet:  # type: ignore  # manager MRO generics
        return super().get_queryset()

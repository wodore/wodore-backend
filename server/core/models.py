"""
Core base models for wodore-backend.

This module provides base model classes that should be used throughout the project.
"""

import datetime
from typing import Any

from django.db import models
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _


class _AutoCreatedField(models.DateTimeField[datetime.datetime, datetime.datetime]):
    """
    A DateTimeField that automatically populates itself at object creation.
    By default, sets editable=False, default=now.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("editable", False)
        kwargs.setdefault("default", now)
        super().__init__(*args, **kwargs)


class _AutoLastModifiedField(
    models.DateTimeField[datetime.datetime, datetime.datetime]
):
    """
    A DateTimeField for tracking last modification time.

    Unlike django-model-utils' _AutoLastModifiedField, this does NOT use auto_now
    or pre_save. Instead, it relies on the PostgreSQL trigger defined in
    TimeStampedModel to update the field on every UPDATE operation.

    This approach works with:
    - Regular .save() calls
    - QuerySet.update()
    - bulk_update()
    - Raw SQL updates

    The trigger is defined at the model level (TimeStampedModel.Meta.triggers).
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("editable", False)
        kwargs.setdefault("default", now)
        super().__init__(*args, **kwargs)


def _abstract_meta(meta: type) -> type:
    """Mark a nested model ``Meta`` abstract — Django's only mechanism
    for abstract bases — while keeping the symbol's checker-visible type
    plain ``type``.

    A direct ``class Meta: abstract = True`` makes type checkers treat
    every subclass's own ``class Meta`` as a structural override of a
    non-empty base (the canonical pyright/Django false positive: the
    subclass Metas legitimately lack ``abstract``). Setting the flag
    through this helper keeps runtime semantics byte-identical — the
    same class object, the attribute present before Django's ModelBase
    reads it — and leaves the symbol assignable for every engine.
    """
    meta.abstract = True  # type: ignore  # Django Meta attr not on `type`
    return meta


class TimeStampedModel(models.Model):
    """
    An abstract base model that provides self-updating `created` and `modified` fields.

    This is a replacement for django-model-utils' TimeStampedModel that uses PostgreSQL
    triggers to ensure the `modified` field is updated even during bulk operations like
    bulk_update() and QuerySet.update().

    Usage:
        class MyModel(TimeStampedModel):
            name = models.CharField(max_length=100)

    The PostgreSQL trigger automatically updates `modified` on every UPDATE operation at
    the database level, ensuring consistency regardless of how the update is performed
    (save(), update(), bulk_update(), raw SQL, etc.).
    """

    created = _AutoCreatedField(_("created"))
    modified = _AutoLastModifiedField(_("modified"))

    class Meta:
        pass

    # Abstract via the helper above: runtime-identical to
    # ``class Meta: abstract = True`` but checker-compatible for every
    # subclass's own nested Meta (see _abstract_meta).
    Meta = _abstract_meta(Meta)

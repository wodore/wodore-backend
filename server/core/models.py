"""
Core base models for wodore-backend.

This module provides base model classes that should be used throughout the project.
"""

from django.db import models
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _


class _AutoCreatedField(models.DateTimeField):
    """
    A DateTimeField that automatically populates itself at object creation.
    By default, sets editable=False, default=now.
    """

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("editable", False)
        kwargs.setdefault("default", now)
        super().__init__(*args, **kwargs)


class _AutoLastModifiedField(models.DateTimeField):
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

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("editable", False)
        kwargs.setdefault("default", now)
        super().__init__(*args, **kwargs)


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
        abstract = True

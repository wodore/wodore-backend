# server/apps/meta_image_field.py

from collections.abc import Sequence
from typing import Any, override

from django import forms
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Model
from django.utils.translation import gettext_lazy as _


class MetaImageField(models.ImageField):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.meta_field: str | None = kwargs.pop("meta_field", None)
        if not self.meta_field:
            raise ValidationError(_("The 'meta_field' argument is required."))
        super().__init__(*args, **kwargs)

    @override
    def contribute_to_class(self, cls: type[Model], name: str, **kwargs: Any) -> None:
        super().contribute_to_class(cls, name, **kwargs)
        fields: list[MetaImageField] | None = getattr(cls, "_meta_image_fields", None)
        if fields is None:
            fields = []
            cls._meta_image_fields = fields
        fields.append(self)

    @override
    def formfield(self, **kwargs: Any) -> forms.Field | None:
        from .forms import MetaImageFormField

        defaults: dict[str, Any] = {"form_class": MetaImageFormField}
        defaults.update(kwargs)
        return super().formfield(**defaults)

    @override
    def deconstruct(self) -> tuple[str, str, Sequence[Any], dict[str, Any]]:
        name, path, args, kwargs = super().deconstruct()
        kwargs["meta_field"] = self.meta_field
        return name, path, args, kwargs

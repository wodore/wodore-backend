# server/apps/meta_image_field.py

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _


class MetaImageField(models.ImageField):
    def __init__(self, *args, **kwargs):
        self.meta_field = kwargs.pop("meta_field", None)
        ## self.meta_field = meta_field
        if not self.meta_field:
            raise ValidationError(_("The 'meta_field' argument is required."))
        super().__init__(*args, **kwargs)

    def contribute_to_class(self, cls, name, **kwargs):
        super().contribute_to_class(cls, name, **kwargs)
        if not hasattr(cls, "_meta_image_fields"):
            cls._meta_image_fields = []
        cls._meta_image_fields.append(self)

    def formfield(self, **kwargs):
        from .forms import MetaImageFormField

        defaults = {"form_class": MetaImageFormField}
        defaults.update(kwargs)
        return super().formfield(**defaults)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        kwargs["meta_field"] = self.meta_field
        return name, path, args, kwargs

from django.conf import settings
from django.utils.translation import gettext_lazy as _

ImageAdminFieldsets = [
    (
        _("Main Information"),
        {
            "fields": [
                "review_status",
                "image",
                "license",
                ("author", "source_org"),
                ("author_url", "source_url"),
                "caption_i18n",
                ("granted_by", "granted_date"),
                ("uploaded_by_anonym", "uploaded_by_user"),
                "tags",
            ],
        },
    ),
    (
        f"{_('Caption')} {_('Translations')}",
        {"classes": [""], "fields": [f"caption_{code}" for code in settings.LANGUAGE_CODES]},
    ),
    (
        _("Meta"),
        {
            "classes": [],
            "fields": [
                ("image_meta"),
            ],
        },
    ),
    (
        _("Timestamps"),
        {
            "classes": ["collapse"],
            "fields": [
                ("created", "modified"),
            ],
        },
    ),
]

from django import forms
from django.core.files.base import ContentFile
from urllib.request import urlopen
from django.core.files.temp import NamedTemporaryFile
from PIL import Image
import io


class ImageUrlOrFileField(forms.ImageField):
    def to_python(self, data):
        print(f"DATA: {data}")
        if data is None:
            return None

        # Handle the case when data is a URL
        if isinstance(data, str):
            try:
                response = urlopen(data)
                image_temp = NamedTemporaryFile(delete=True)
                image_temp.write(response.read())
                image_temp.flush()
                image = Image.open(io.BytesIO(image_temp.read()))
                content_file = ContentFile(image_temp.read())
                return content_file
            except Exception as e:
                raise forms.ValidationError("The URL provided could not be retrieved: %s" % e)

        # Handle the case when data is an uploaded file
        return super().to_python(data)

    def validate(self, value):
        # Only perform validation if value is a file, skip validation for URLs
        if isinstance(value, ContentFile):
            return
        super().validate(value)


from django.db import models


class CustomImageField(models.ImageField):
    def formfield(self, **kwargs):
        print("Set formfield to ImageUrlOrFileField")
        defaults = {"form_class": ImageUrlOrFileField}
        defaults.update(kwargs)
        print(defaults)
        return super().formfield(**defaults)

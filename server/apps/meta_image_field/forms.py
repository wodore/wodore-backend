from urllib import request

from django import forms
from django.core.files.base import ContentFile

from .widgets import MetaImageWidget


class MetaImageFormField(forms.ImageField):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.widget = MetaImageWidget()

    def to_python(self, data):
        # print(f"DATA: {type(data)} - {data}")
        # Add custom logic to handle both file uploads and URL-based images
        if isinstance(data, str) and data.startswith("http"):
            try:
                response = request.urlopen(data)
                data = ContentFile(response.read(), name=data.split("/")[-1])
            except Exception as e:
                raise forms.ValidationError(f"Unable to download image: {e}")
        return super().to_python(data)

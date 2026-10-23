from urllib import request

from django import forms
from django.core.files.base import ContentFile

from .widgets import MetaImageWidget


def _sanitize_file_name(name: str) -> str:
    """ASCII-safe, imagor-safe file name.

    Unicode names (e.g. ``Lämmeren_hut.jpg`` from a decoded raw URL) break
    imagor's file lookup because the request path is percent-encoded once
    more than the on-disk name expects.
    """
    import os
    import re
    import unicodedata

    base, ext = os.path.splitext(os.path.basename(name))
    base = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode()
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._") or "image"
    return f"{base}{ext.lower() or '.jpg'}"


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
                data = ContentFile(
                    response.read(), name=_sanitize_file_name(data.split("/?")[-1])
                )
            except Exception as e:
                raise forms.ValidationError(f"Unable to download image: {e}")
        elif data is not None and hasattr(data, "name") and data.name:
            if data.name != _sanitize_file_name(data.name):
                data = ContentFile(data.read(), name=_sanitize_file_name(data.name))
        return super().to_python(data)

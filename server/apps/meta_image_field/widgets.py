from typing import ClassVar

from django.forms.widgets import ClearableFileInput


class MetaImageWidget(ClearableFileInput):
    template_name = "meta_image_field/meta_image_widget.html"

    class Media:
        css: ClassVar[dict] = {"all": ("meta_image_field/css/jcrop.css", "meta_image_field/css/style.css")}
        js: ClassVar[tuple] = ("meta_image_field/js/jcrop.js", "meta_image_field/js/meta_image_widget.js")

    def __init__(self, attrs=None):
        default_attrs = {"class": "meta-image-input"}
        if attrs:
            default_attrs.update(attrs)
        super().__init__(default_attrs)

    def value_from_datadict(self, data, files, name):
        # print(f"Values FROM DICT '{name}': {data}")
        # print(f"Files FROM DICT: {files}")
        upload = super().value_from_datadict(data, files, name)
        # print(f"UPLOAD: {upload}")
        if not upload:
            url = data.get(f"{name}_url")
            if url:
                return url
        return upload

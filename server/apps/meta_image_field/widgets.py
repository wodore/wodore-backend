from collections.abc import Mapping, Sequence
from typing import Any, ClassVar, override

from django.core.files.uploadedfile import UploadedFile
from django.forms.widgets import ClearableFileInput
from django.utils.datastructures import MultiValueDict


class MetaImageWidget(ClearableFileInput):
    template_name = "meta_image_field/meta_image_widget.html"

    class Media:
        css: ClassVar[dict[str, Sequence[str]]] = {
            "all": ("meta_image_field/css/jcrop.css", "meta_image_field/css/style.css")
        }
        js: ClassVar[tuple[str, ...]] = (
            "meta_image_field/js/jcrop.js",
            "meta_image_field/js/meta_image_widget.js",
        )

    def __init__(self, attrs: dict[str, Any] | None = None) -> None:
        default_attrs = {"class": "meta-image-input"}
        if attrs:
            default_attrs.update(attrs)
        super().__init__(default_attrs)

    @override
    def value_from_datadict(
        self,
        data: Mapping[str, Any],
        files: MultiValueDict[str, UploadedFile[Any]],
        name: str,
    ) -> Any:
        # print(f"Values FROM DICT '{name}': {data}")
        # print(f"Files FROM DICT: {files}")
        upload = super().value_from_datadict(data, files, name)
        # print(f"UPLOAD: {upload}")
        if not upload:
            url = data.get(f"{name}_url")
            if url:
                return url
        return upload

    @override
    def get_context(
        self, name: str, value: Any, attrs: dict[str, Any] | None
    ) -> dict[str, Any]:
        context = super().get_context(name, value, attrs)
        # External fallback for pinned images (no local file): the admin sets
        # `raw_url` (the instance's source_url_raw) so the template can render
        # the raw preview — focal point selection then works like on uploads.
        context["widget"]["raw_url"] = getattr(self, "raw_url", None)
        return context

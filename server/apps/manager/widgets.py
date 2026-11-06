from typing import Any, override

from jsonsuit.widgets import JSONSuit, ReadonlyJSONSuit

from django.forms.renderers import BaseRenderer
from django.template.loader import render_to_string
from django.utils.safestring import SafeString

from unfold.widgets import BASE_INPUT_CLASSES


class UnfoldJSONSuit(JSONSuit):
    @override
    def render(
        self,
        name: str,
        value: Any,
        attrs: dict[str, Any] | None = None,
        renderer: BaseRenderer | None = None,
    ) -> SafeString:
        klass = " ".join(BASE_INPUT_CLASSES)
        attrs = attrs or {}
        attrs.update({"class": "hidden " + klass})

        textarea = super(JSONSuit, self).render(name, value, attrs)
        return render_to_string(
            "jsonsuit/widget.html",
            {
                "name": name,
                "value": value,
                "textarea": textarea,
                "view_class": " ".join(BASE_INPUT_CLASSES),
            },
        )


class UnfoldReadonlyJSONSuit(ReadonlyJSONSuit):
    @override
    def render(
        self,
        name: str,
        value: Any,
        attrs: dict[str, Any] | None = None,
        renderer: BaseRenderer | None = None,
    ) -> SafeString:
        klass = " ".join(BASE_INPUT_CLASSES)
        attrs = attrs or {}
        attrs.update({"class": "hidden " + klass})
        return render_to_string(
            "jsonsuit/readonly_widget.html",
            {
                "name": name,
                "value": value,
                "attrs": attrs,
                "view_class": " ".join(BASE_INPUT_CLASSES),
            },
        )

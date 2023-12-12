from django.template.loader import render_to_string
from jsonsuit.widgets import JSONSuit, ReadonlyJSONSuit
from unfold.widgets import BASE_INPUT_CLASSES


class UnfoldJSONSuit(JSONSuit):
    def render(self, name, value, attrs={}, renderer=None):
        klass = " ".join(BASE_INPUT_CLASSES)
        attrs.update({"class": "hidden " + klass})

        textarea = super(JSONSuit, self).render(name, value, attrs)
        return render_to_string(
            "jsonsuit/widget.html",
            {"name": name, "value": value, "textarea": textarea, "view_class": " ".join(BASE_INPUT_CLASSES)},
        )


class UnfoldReadonlyJSONSuit(ReadonlyJSONSuit):
    def render(self, name, value, attrs=None, renderer=None):
        klass = " ".join(BASE_INPUT_CLASSES)
        attrs = attrs or {}
        attrs.update({"class": "hidden " + klass})
        return render_to_string(
            "jsonsuit/readonly_widget.html",
            {"name": name, "value": value, "attrs": attrs, "view_class": " ".join(BASE_INPUT_CLASSES)},
        )

import json

from django import forms
from django.utils.translation import gettext_lazy as _

CHOICES = [
    ("yes", _("Yes")),
    ("yesish", f"({_('Yes')})"),
    ("maybe", _("Maybe")),
    ("noish", f"({_('No')})"),
    ("no", _("No")),
    ("unknown", "?"),
]

MONTHS = [
    ("month_01", _("January")),
    ("month_02", _("February")),
    ("month_03", _("March")),
    ("month_04", _("April")),
    ("month_05", _("May")),
    ("month_06", _("June")),
    ("month_07", _("July")),
    ("month_08", _("August")),
    ("month_09", _("September")),
    ("month_10", _("October")),
    ("month_11", _("November")),
    ("month_12", _("December")),
]


class OpenMonthlyWidget(forms.Widget):
    template_name = "admin/widgets/open_monthly.html"

    class Media:
        css = {"all": ("admin/css/open_monthly.css",)}
        js = ("admin/js/open_monthly.js",)

    def get_context(self, name, value, attrs):
        """Prepare context for rendering the widget."""
        context = super().get_context(name, value, attrs)
        if isinstance(value, str) and value.strip():
            try:
                value = json.loads(value)  # Convert string to dict if necessary
            except json.JSONDecodeError:
                value = {}
        data = value or {}
        print("DATA context:", json.dumps(data, indent=2))

        context["widget"] = {
            "name": name,
            "url": data.get("url", ""),
            "months": [
                (key, month_name, data.get(key, "unknown"))
                for key, month_name in MONTHS
            ],
            "choices": CHOICES,
        }
        return context

    def value_from_datadict(self, data, files, name):
        """Retrieve and format data from form submission."""
        print("DATA from datadict:", json.dumps(data, indent=2))
        result = {"url": data.get(f"{name}_url", "")}
        for key, _v in MONTHS:
            result[key] = data.get(f"{name}_{key}", "unknown")
        print("result:", json.dumps(result, indent=2))
        return result


#
#
# from django import forms
# from django.utils.safestring import mark_safe
#
# CHOICES = [
#    ("yes", "Yes"),
#    ("yesish", "Yesish"),
#    ("maybe", "Maybe"),
#    ("no", "No"),
#    ("noish", "Noish"),
#    ("unknown", "Unknown"),
# ]
#
#
# class OpenMonthlyWidget(forms.Widget):
#    template_name = "admin/widgets/open_monthly.html"
#
#    def get_context(self, name, value, attrs):
#        """Prepare context for rendering."""
#        context = super().get_context(name, value, attrs)
#        data = value if isinstance(value, dict) else {}
#        context["widget"] = {
#            "url": data.get("url", ""),
#            "months": [(f"month_{i:02d}", data.get(f"month_{i:02d}", "unknown")) for i in range(1, 13)],
#            "choices": CHOICES,
#        }
#        return contex
#
#    def render(self, name, value, attrs=None, renderer=None):
#        data = value if isinstance(value, dict) else {}
#
#        html = '<div class="unfold-form-group">'
#        html += '<label class="unfold-label">URL:</label>'
#        html += f'<input type="text" name="{name}_url" value="{data.get("url", "")}" class="unfold-input" /></div>'
#
#        # "Select All" row
#        html += '<div class="unfold-form-group">'
#        html += '<label class="unfold-label">Select All:</label>'
#        for choice_value, choice_label in CHOICES:
#            html += f'<input type="radio" name="{name}_select_all" value="{choice_value}" onclick="selectAllMonths(this, \'{name}\')" /> {choice_label}'
#        html += "</div>"
#
#        # Monthly fields
#        for i in range(1, 13):
#            month_key = f"month_{i:02d}"
#            selected_value = data.get(month_key, "unknown")
#
#            html += '<div class="unfold-form-group">'
#            html += f'<label class="unfold-label">{month_key.replace("_", " ").title()}:</label>'
#            for choice_value, choice_label in CHOICES:
#                checked = 'checked="checked"' if choice_value == selected_value else ""
#                html += f'<input type="radio" name="{name}_{month_key}" value="{choice_value}" {checked} class="unfold-radio"/> {choice_label}'
#            html += "</div>"
#
#        # JavaScript for "Select All"
#        html += """
#        <script>
#            function selectAllMonths(selectAll, name) {
#                let radios = document.querySelectorAll(`input[name^="${name}_month_"]`);
#                radios.forEach(radio => {
#                    if (radio.value === selectAll.value) {
#                        radio.checked = true;
#                    }
#                });
#            }
#        </script>
#        """
#
#        return mark_safe(html)
#
#    def value_from_datadict(self, data, files, name):
#        """Retrieve and format data from form submission."""
#        result = {"url": data.get(f"{name}_url", "")}
#        for i in range(1, 13):
#            month_key = f"month_{i:02d}"
#            result[month_key] = data.get(f"{name}_{month_key}", "unknown")
#        return result
#

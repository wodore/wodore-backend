"""Custom admin widgets for geo command arguments."""

from django import forms


class BBoxWidget(forms.TextInput):
    """Text input plus an OpenLayers map to draw the bounding box.

    Value format: ``lon_min,lat_min,lon_max,lat_max`` (WGS84 degrees).
    Shift+drag on the map draws the rectangle, or type the four
    coordinates; the map and the input stay in sync. The widget template
    is self-contained (loads OpenLayers itself), because the admin
    runner's run form does not render ``{{ form.media }}``.
    """

    template_name = "geometries/widgets/bbox.html"

    class Media:
        css = {
            "all": (
                "https://cdn.jsdelivr.net/npm/ol@v10.9.0/ol.css",
                "gis/css/ol3.css",
            )
        }
        js = (
            "https://cdn.jsdelivr.net/npm/ol@v10.9.0/dist/ol.js",
            "geometries/js/bbox_widget.js",
        )

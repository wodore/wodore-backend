"""Darker transport colors: the light pack shades washed out on the map.

Owner decision (2026-11-16, after #502 shipped): the category colors
taken verbatim from the icon artwork (migration 0026) include shades
too light for map use — as SDF icon tints and small circles on the
pale outdoor basemap they read as ghosted/semi-transparent (ferry
``#64bbdf``, metro ``#4dbaf6``, cablecar/gondola ``#a0e5a5``,
funicular ``#678d98`` all under ~3.6:1 contrast against the basemap;
rail/bus sit at 5.4–6.5:1). This migration moves those few entries to
darker shades **within the same hue family** (all ≥ ~4.6:1), keeping
one color per kind everywhere (legend, circles, icon tint).

``seed_lib.TRANSPORT_FALLBACK_COLORS`` mirrors the route-type entries
(fresh-install parity — keep in sync, same doctrine as 0022/0026).
Re-run ``map_seed`` afterwards to rotate the style version.
"""

from typing import Any

from django.db import migrations

#: kind slug → darker same-hue shade (contrast-checked against the
#: pale outdoor basemap ≈ #e8eae2; reference band rail/bus 5.4–6.5:1).
CONTRAST_COLORS: dict[str, str] = {
    "ferry": "#14618d",  # 5.5:1 (was #64bbdf)
    "metro": "#0b5ea6",  # 5.5:1 (was #4dbaf6)
    "cablecar": "#27703c",  # 5.0:1 (was #a0e5a5)
    "gondola": "#27703c",  # 5.0:1 (was #a0e5a5)
    "funicular": "#4b7285",  # ~4.6:1 (was #678d98)
    "airport": "#0e6f9e",  # 4.6:1 (was #72d8ff; legend-only kind)
}


def recolor(apps: Any, _schema_editor: Any) -> None:
    Category = apps.get_model("categories", "Category")

    group = Category.objects.filter(slug="transport", parent__slug="transport").first()
    if group is None:
        return

    for slug, color in CONTRAST_COLORS.items():
        child = group.children.filter(slug=slug).first()
        if child is not None:
            child.color = color
            child.save(update_fields=["color"])

    # the group node (and its light green) rides along
    group.color = "#3f7d28"
    group.save(update_fields=["color"])


def uncolor(apps: Any, _schema_editor: Any) -> None:
    """Best-effort reverse: back to the 0026 pack shades."""
    Category = apps.get_model("categories", "Category")

    old = {
        "ferry": "#64bbdf",
        "metro": "#4dbaf6",
        "cablecar": "#a0e5a5",
        "gondola": "#a0e5a5",
        "funicular": "#678d98",
        "airport": "#72d8ff",
        "transport": "#ade194",
    }
    group = Category.objects.filter(slug="transport", parent__slug="transport").first()
    if group is None:
        return
    for slug, color in old.items():
        row = group if slug == "transport" else group.children.filter(slug=slug).first()
        if row is not None:
            row.color = color
            row.save(update_fields=["color"])


class Migration(migrations.Migration):
    dependencies = [
        ("categories", "0026_transport_colors_from_pack"),
    ]

    operations = [
        migrations.RunPython(recolor, uncolor),
    ]

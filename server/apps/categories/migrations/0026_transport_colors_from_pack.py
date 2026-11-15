"""Transport category colors aligned with the icon pack artwork.

Owner decision (2026-11-12, post-#501): the legend/category colors must
match the dominant fill of each kind's approved color icon from the
transport iconpilot pack — the former palette (SBB red rail, Post blue
bus, purple metro, …) diverged from the glyphs the overlay now renders,
and the non-route kinds (airport, bus_station, chairlift) all carried
the model-default green.

Colors are the pack's ``main_color`` values (aliases inherit their
glyph source's color by pack contract: bus_station/trolleybus = bus,
gondola = cablecar, monorail = tram).

``seed_lib.TRANSPORT_FALLBACK_COLORS`` mirrors the same values (fresh
install parity — keep in sync, same doctrine as 0022). Re-run
``map_seed`` after deploying so the overlay style rotates to the new
palette.

Unconditional on purpose: this is an owner-curated recolor, not a
default-fill guard (0022's guard protected curator colors; here the
owner is setting them).
"""

from typing import Any

from django.db import migrations

#: transport kind slug → pack main_color (iconpacks/transport/pack.json).
PACK_COLORS: dict[str, str] = {
    "rail": "#4a5359",
    "bus": "#475a99",
    "bus_station": "#475a99",
    "metro": "#4dbaf6",
    "tram": "#35495d",
    "cablecar": "#a0e5a5",
    "gondola": "#a0e5a5",
    "funicular": "#678d98",
    "trolleybus": "#475a99",
    "monorail": "#35495d",
    "ferry": "#64bbdf",
    "airport": "#72d8ff",
    "chairlift": "#a79ba7",
    "parking": "#3f597d",
}


def recolor(apps: Any, _schema_editor: Any) -> None:
    Category = apps.get_model("categories", "Category")

    group = Category.objects.filter(slug="transport", parent__slug="transport").first()
    if group is None:
        return  # tree not seeded here

    for slug, color in PACK_COLORS.items():
        child = group.children.filter(slug=slug).first()
        if child is not None:
            child.color = color
            child.save(update_fields=["color"])

    # the group node itself carries the generic glyph's color
    group.color = "#ade194"
    group.save(update_fields=["color"])


def uncolor(apps: Any, schema_editor: Any) -> None:
    """Best-effort reverse: back to the pre-0022/0025 palette."""
    Category = apps.get_model("categories", "Category")
    old = {
        "rail": "#C60018",
        "bus": "#2d327d",
        "bus_station": "#4B8E43",
        "metro": "#7B1FA2",
        "tram": "#00838F",
        "cablecar": "#FF8F00",
        "gondola": "#D81B60",
        "funicular": "#795548",
        "trolleybus": "#9E9D24",
        "monorail": "#455A64",
        "ferry": "#0079C7",
        "airport": "#4B8E43",
        "chairlift": "#4B8E43",
        "parking": "#5d748a",
        "transport": "#e19974",
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
        ("categories", "0025_transport_domain_transitland_kinds"),
    ]

    operations = [
        migrations.RunPython(recolor, uncolor),
    ]

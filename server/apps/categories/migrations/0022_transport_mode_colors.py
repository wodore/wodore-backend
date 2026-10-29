"""Transport-mode colors for the transport-stops map overlay.

The overlay (basemaps `transport-stops`, Transitland vector tiles)
paints stops by GTFS route type and resolves its legend/filter from the
`transport` category tree — the tree's children carried the model
default green since geometries.0002 seeded them, so legend chips and
map circles had no distinct colors to share. This migration sets the
five route-mode children (train/bus/metro/tram/ferry) to the overlay
palette; `map_seed` bakes the same values into the style at seed time
(seed_lib.TRANSPORT_FALLBACK_COLORS parity — keep them in sync).

Guarded: only rows still on the model default are recolored, so a
curator's own colors always win (re-run `map_seed` afterwards to rotate
the style version).
"""

from typing import Any

from django.db import migrations

#: transport child slug → color (seed_lib.TRANSPORT_FALLBACK_COLORS parity).
MODE_COLORS = {
    "train_station": "#C60018",  # SBB red
    "bus_stop": "#2d327d",  # Post blue
    "metro_station": "#7B1FA2",
    "tram_stop": "#00838F",
    "ferry": "#0079C7",
}

#: The Category.color model default (colorfield) — the "never curated"
#: sentinel; anything else is operator intent and stays untouched.
MODEL_DEFAULT = "#4B8E43"


def set_transport_mode_colors(apps: Any, _schema_editor: Any) -> None:
    Category = apps.get_model("categories", "Category")
    for slug, color in MODE_COLORS.items():
        updated = Category.objects.filter(
            slug=slug,
            parent__slug="transport",
            color=MODEL_DEFAULT,
        ).update(color=color)
        if updated:
            print(f"✓ transport.{slug}: color → {color}")


def restore_defaults(apps: Any, _schema_editor: Any) -> None:
    Category = apps.get_model("categories", "Category")
    for slug, color in MODE_COLORS.items():
        Category.objects.filter(
            slug=slug,
            parent__slug="transport",
            color=color,
        ).update(color=MODEL_DEFAULT)


class Migration(migrations.Migration):
    dependencies = [
        ("categories", "0021_category_created_category_modified_and_more"),
        # The transport tree itself (children) comes from geometries:
        # depends on the seeding migration so the rows exist.
        ("geometries", "0002_create_geoplace_categories"),
    ]

    operations = [
        migrations.RunPython(set_transport_mode_colors, restore_defaults),
    ]

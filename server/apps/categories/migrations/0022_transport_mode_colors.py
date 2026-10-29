"""Transport-mode categories for the transport-stops map overlay.

The overlay (basemaps `transport-stops`, Transitland vector tiles)
paints stops by GTFS route type and resolves its legend/filter from the
`transport` category tree — so the tree must cover exactly what
Transitland's `route_types_basic` can carry: all ten basic GTFS types
(0 tram, 1 metro, 2 rail, 3 bus, 4 ferry, 5 cable tram, 6 aerial lift,
7 funicular, 11 trolleybus, 12 monorail).

This migration:

* colors the five route-mode children that existed since
  geometries.0002 but carried the model default green
  (train/bus/metro/tram/ferry),
* colors the three lift children (cable_car, gondola, funicular) —
  they were place categories before; GTFS 5/6/7 now render through
  them,
* creates the two missing children `trolleybus` (11) and `monorail`
  (12) — no basic GTFS type stays unrendered.

`map_seed` bakes the same values into the style at seed time
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
    "cable_car": "#FF8F00",  # GTFS 5 cable tram
    "gondola": "#D81B60",  # GTFS 6 aerial lift
    "funicular": "#795548",  # GTFS 7
    "trolleybus": "#9E9D24",  # GTFS 11
    "monorail": "#455A64",  # GTFS 12
}

#: The Category.color model default (colorfield) — the "never curated"
#: sentinel; anything else is operator intent and stays untouched.
MODEL_DEFAULT = "#4B8E43"

#: The two children geometries.0002 never seeded (no geoplace feature
#: mapping needed them): the GTFS types 11 and 12. Shape follows the
#: geometries.0002 child tuples (de name/description + i18n dict, order).
NEW_CHILDREN: tuple[tuple[str, str, str, dict[str, str], int], ...] = (
    (
        "trolleybus",
        "Trolleybus-Haltestelle",
        "Trolleybus-Haltestelle",
        {
            "name_en": "Trolleybus Stop",
            "name_fr": "Arrêt de trolleybus",
            "name_it": "Fermata del filobus",
            "description_en": "Trolleybus (electric overhead-wire bus) stop",
            "description_fr": "Arrêt de trolleybus (bus électrique à fil)",
            "description_it": "Fermata del filobus (bus elettrico a filo)",
        },
        80,
    ),
    (
        "monorail",
        "Monorail-Station",
        "Monorail-Station",
        {
            "name_en": "Monorail Station",
            "name_fr": "Station de monorail",
            "name_it": "Stazione della monorotaia",
            "description_en": "Monorail station or stop",
            "description_fr": "Station ou arrêt de monorail",
            "description_it": "Stazione o fermata della monorotaia",
        },
        90,
    ),
)


def set_transport_mode_categories(apps: Any, _schema_editor: Any) -> None:
    Category = apps.get_model("categories", "Category")
    parent = Category.objects.filter(slug="transport", parent=None).first()

    for slug, color in MODE_COLORS.items():
        updated = Category.objects.filter(
            slug=slug,
            parent__slug="transport",
            color=MODEL_DEFAULT,
        ).update(color=color)
        if updated:
            print(f"✓ transport.{slug}: color → {color}")

    if parent is None:
        print("⚠ transport root missing — skipping new children")
        return
    for slug, name, description, i18n, order in NEW_CHILDREN:
        child, created = Category.objects.get_or_create(
            slug=slug,
            parent=parent,
            defaults={
                "name": name,
                "description": description,
                "order": order,
                "is_active": True,
                "color": MODE_COLORS[slug],
            },
        )
        if created:
            child.i18n = i18n
            child.save()
            print(f"✓ transport.{slug}: created (color {MODE_COLORS[slug]})")


def restore_defaults(apps: Any, _schema_editor: Any) -> None:
    Category = apps.get_model("categories", "Category")
    for slug, color in MODE_COLORS.items():
        Category.objects.filter(
            slug=slug,
            parent__slug="transport",
            color=color,
        ).update(color=MODEL_DEFAULT)
    # Drop only the children this migration created (order/is_active
    # match the seeded shape — a curator-reworked row keeps its slug
    # but loses the guard; acceptable for a feature-branch migration).
    Category.objects.filter(
        slug__in=[slug for slug, *_ in NEW_CHILDREN],
        parent__slug="transport",
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("categories", "0021_category_created_category_modified_and_more"),
        # The transport tree itself (children) comes from geometries:
        # depends on the seeding migration so the rows exist.
        ("geometries", "0002_create_geoplace_categories"),
    ]

    operations = [
        migrations.RunPython(set_transport_mode_categories, restore_defaults),
    ]

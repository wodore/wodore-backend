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

The basic GTFS route type is also mirrored into each mode child's
``extra`` (``{"gtfs_route_type": N}``, merged — never clobbering other
keys) so admin/other apps can read the pairing data-side. The CODE-side
mapping stays authoritative and fast: `seed_lib.TRANSPORT_MODES` builds
the style without a DB round-trip; the extras are documentation kept in
sync here (test-pinned against TRANSPORT_MODES).
"""

from typing import Any

from django.db import migrations

#: transport child slug → (color, basic GTFS route type)
#: (seed_lib.TRANSPORT_FALLBACK_COLORS / TRANSPORT_MODES parity).
MODES: dict[str, tuple[str, int]] = {
    "train_station": ("#C60018", 2),  # SBB red · rail
    "bus_stop": ("#2d327d", 3),  # Post blue · bus
    "metro_station": ("#7B1FA2", 1),
    "tram_stop": ("#00838F", 0),
    "ferry": ("#0079C7", 4),
    "cable_car": ("#FF8F00", 5),  # cable tram
    "gondola": ("#D81B60", 6),  # aerial lift
    "funicular": ("#795548", 7),
    "trolleybus": ("#9E9D24", 11),
    "monorail": ("#455A64", 12),
}

#: Flat color view for the recolor pass below.
MODE_COLORS = {slug: color for slug, (color, _code) in MODES.items()}

#: The ``extra`` key carrying the basic GTFS route type.
GTFS_EXTRA_KEY = "gtfs_route_type"

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

    for slug, (color, gtfs_type) in MODES.items():
        for child in Category.objects.filter(
            slug=slug, parent__slug="transport"
        ).only("color", "extra"):
            if child.color == MODEL_DEFAULT:
                child.color = color
                print(f"✓ transport.{slug}: color → {color}")
            # Mirror the basic GTFS route type into ``extra`` (merged —
            # other keys the row carries stay untouched). Row-wise on
            # purpose: a handful of rows, and stock Django has no
            # typed JSONB merge/remove expressions.
            merged = {**(child.extra or {}), GTFS_EXTRA_KEY: gtfs_type}
            if merged != child.extra:
                child.extra = merged
            child.save(update_fields=["color", "extra"])
    if parent is not None:
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
                    "extra": {GTFS_EXTRA_KEY: MODES[slug][1]},
                },
            )
            if created:
                child.i18n = i18n
                child.save()
                print(
                    f"✓ transport.{slug}: created (color {MODE_COLORS[slug]})"
                )
    else:
        print("⚠ transport root missing — skipping new children")


def restore_defaults(apps: Any, _schema_editor: Any) -> None:
    from django.db import connection

    Category = apps.get_model("categories", "Category")
    for slug, color in MODE_COLORS.items():
        for child in Category.objects.filter(
            slug=slug, parent__slug="transport"
        ).only("color", "extra"):
            if child.color == color:
                child.color = MODEL_DEFAULT
            extras = dict(child.extra or {})
            if extras.pop(GTFS_EXTRA_KEY, None) is not None:
                child.extra = extras
            child.save(update_fields=["color", "extra"])
    # Raw SQL on purpose: the ORM deletion collector walks related
    # GeoPlace rows and resolves their modeltrans ``name_i18n`` Meta
    # ordering — a runtime descriptor that does not exist on
    # historical migration models (FieldError). The DB-level ON
    # DELETE CASCADE on the M2M join tables takes care of
    # associations; the created children carry none anyway.
    slugs = tuple(slug for slug, *_ in NEW_CHILDREN)
    with connection.cursor() as cursor:
        cursor.execute(
            "DELETE FROM categories_category c USING categories_category p "
            "WHERE c.parent_id = p.id AND p.slug = %s AND p.parent_id IS NULL "
            "AND c.slug = ANY(%s)",
            ["transport", list(slugs)],
        )


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

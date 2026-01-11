# Generated manually on 2026-01-11

from django.db import migrations


def assign_feature_categories(apps, schema_editor):
    """
    Assign categories to GeoNames features based on the mapping defined in
    server/apps/categories/geonames_category_mapping.ods
    """
    Feature = apps.get_model("external_geonames", "Feature")
    Category = apps.get_model("categories", "Category")

    # Feature to category mapping: feature_id -> (parent_slug, child_slug)
    # Based on geonames_category_mapping.ods
    feature_category_mapping = {
        # Terrain features
        "T.PK": ("terrain", "peak"),
        "T.PKS": ("terrain", "peak"),
        "T.MT": ("terrain", "peak"),
        "T.MTS": ("terrain", "peak"),
        "T.PASS": ("terrain", "pass"),
        "T.SDL": ("terrain", "pass"),
        "T.VAL": ("terrain", "valley"),
        "T.VALS": ("terrain", "valley"),
        "T.PLAT": ("terrain", "plateau"),
        "T.PLTU": ("terrain", "plateau"),
        "T.RDG": ("terrain", "ridge"),
        "T.RDGE": ("terrain", "ridge"),
        "T.GRGE": ("terrain", "gorge"),
        "T.CNYN": ("terrain", "gorge"),
        "T.HLL": ("terrain", "hill"),
        "T.HLLS": ("terrain", "hill"),
        "T.SPUR": ("terrain", "spur"),
        "T.CAPE": ("terrain", "cape"),
        "T.PT": ("terrain", "cape"),
        "T.ISL": ("terrain", "island"),
        "T.ISLS": ("terrain", "island"),
        "T.ATOL": ("terrain", "island"),

        # Hydrographic features
        "H.LK": ("hydrographic", "lake"),
        "H.LKS": ("hydrographic", "lake"),
        "H.LKN": ("hydrographic", "lake"),
        "H.LKSN": ("hydrographic", "lake"),
        "H.PNDN": ("hydrographic", "lake"),
        "H.PND": ("hydrographic", "lake"),
        "H.PNDS": ("hydrographic", "lake"),
        "H.POOL": ("hydrographic", "lake"),
        "H.FLLS": ("hydrographic", "waterfall"),
        "H.GLCR": ("hydrographic", "glacier"),
        "H.STM": ("hydrographic", "stream"),
        "H.STMS": ("hydrographic", "stream"),
        "H.STMX": ("hydrographic", "stream"),
        "H.STMI": ("hydrographic", "stream"),
        "H.STMH": ("hydrographic", "stream"),
        "H.STMM": ("hydrographic", "stream"),
        "H.STMQ": ("hydrographic", "stream"),
        "H.RVNQ": ("hydrographic", "stream"),
        "H.CNLN": ("hydrographic", "stream"),
        "H.CNL": ("hydrographic", "stream"),
        "H.CNLA": ("hydrographic", "stream"),
        "H.CNLSB": ("hydrographic", "stream"),
        "H.DTCH": ("hydrographic", "stream"),
        "H.RSV": ("hydrographic", "reservoir"),
        "H.RSVI": ("hydrographic", "reservoir"),
        "H.RSVT": ("hydrographic", "reservoir"),
        "H.BAY": ("hydrographic", "bay"),
        "H.BAYS": ("hydrographic", "bay"),
        "H.GULF": ("hydrographic", "bay"),
        "H.COVE": ("hydrographic", "bay"),

        # Populated places
        "P.PPL": ("populated_place", "village"),
        "P.PPLA": ("populated_place", "city"),
        "P.PPLA2": ("populated_place", "city"),
        "P.PPLA3": ("populated_place", "town"),
        "P.PPLA4": ("populated_place", "village"),
        "P.PPLA5": ("populated_place", "village"),
        "P.PPLC": ("populated_place", "capital"),
        "P.PPLCH": ("populated_place", "capital"),
        "P.PPLL": ("populated_place", "village"),
        "P.PPLQ": ("populated_place", "village"),
        "P.PPLX": ("populated_place", "village"),

        # Administrative
        "L.RGN": ("administrative", "region"),
        "L.RGNE": ("administrative", "region"),
        "L.RGNL": ("administrative", "region"),

        # Transport
        "S.RSTN": ("transport", "train_station"),
        "S.RSTP": ("transport", "train_station"),
        "S.BUSTN": ("transport", "bus_stop"),
        "S.BUSTP": ("transport", "bus_stop"),
        "S.MTRO": ("transport", "metro_station"),
        "S.TRAM": ("transport", "tram_stop"),
        "S.AIRP": ("transport", "airport"),
        "S.AIRF": ("transport", "airport"),
        "S.AIRH": ("transport", "airport"),
        "S.AIRQ": ("transport", "airport"),
        "S.FY": ("transport", "ferry"),
        "S.FYT": ("transport", "ferry"),
        "S.PKLT": ("transport", "parking"),
        "S.PKG": ("transport", "parking"),

        # Accommodation
        "S.REST": ("accommodation", "restaurant"),
        "S.HTL": ("accommodation", "restaurant"),

        # Spot/POI
        "S.CH": ("spot", "church"),
        "S.CSTL": ("spot", "castle"),
        "S.PAL": ("spot", "castle"),
        "S.OBPT": ("spot", "viewpoint"),
        "S.OBS": ("spot", "viewpoint"),
        "S.CAVE": ("spot", "cave"),
        "S.CVNT": ("spot", "cave"),
        "S.MUS": ("spot", "museum"),
        "S.RECG": ("spot", "recreation"),
        "S.RECR": ("spot", "recreation"),
        "S.PRK": ("spot", "park"),
        "S.GRVE": ("spot", "park"),
        "S.DAM": ("spot", "dam"),
        "S.DAMSB": ("spot", "dam"),
    }

    # Build a lookup map of categories
    category_map = {}
    for parent_slug, child_slug in set(feature_category_mapping.values()):
        try:
            parent = Category.objects.get(slug=parent_slug, parent=None)
            child = Category.objects.get(slug=child_slug, parent=parent)
            category_map[(parent_slug, child_slug)] = child
        except Category.DoesNotExist:
            print(f"  WARNING: Category not found for {parent_slug}.{child_slug}")

    # Assign categories to features
    print("Assigning categories to GeoNames features...")
    mapped_count = 0
    not_found_count = 0

    for feature_id, (parent_slug, child_slug) in feature_category_mapping.items():
        category = category_map.get((parent_slug, child_slug))
        if not category:
            print(f"  WARNING: Category not found for {parent_slug}.{child_slug}")
            continue

        try:
            feature = Feature.objects.get(id=feature_id)
            feature.category = category
            feature.save(update_fields=["category"])
            mapped_count += 1
            print(f"  Mapped {feature_id} -> {parent_slug}.{child_slug}")
        except Feature.DoesNotExist:
            not_found_count += 1
            print(f"  WARNING: Feature {feature_id} not found (will be created later)")

    print(f"\nCompleted: Mapped {mapped_count} features, {not_found_count} features not found yet")


def reverse_feature_categories(apps, schema_editor):
    """Clear category assignments from features."""
    Feature = apps.get_model("external_geonames", "Feature")
    Feature.objects.filter(category__isnull=False).update(category=None)


class Migration(migrations.Migration):

    dependencies = [
        ("external_geonames", "0007_feature_category"),
        ("categories", "0003_rename_symbol_fields"),
        ("geometries", "0002_create_geoplace_categories"),
    ]

    operations = [
        migrations.RunPython(assign_feature_categories, reverse_code=reverse_feature_categories),
    ]

# Generated manually on 2026-01-10

from django.db import migrations


def create_categories_and_map_features(apps, schema_editor):
    """
    Create categories for GeoPlace and map GeoNames features to them.

    Creates parent categories (terrain, hydrographic, populated_place, etc.)
    and child categories (peak, lake, village, etc.), then maps enabled
    GeoNames features to the appropriate categories.

    Note: Symbols are handled by categories.0009_migrate_category_symbols
    which runs before this migration (see dependency on categories.0010).
    """
    Category = apps.get_model("categories", "Category")
    Feature = apps.get_model("external_geonames", "Feature")

    # Parent categories configuration with German names and translations
    parent_categories = [
        {
            "slug": "terrain",
            "name": "Gelände",
            "description": "Berge, Gipfel, Täler und andere Geländeformen",
            "i18n": {
                "name_en": "Terrain",
                "name_fr": "Terrain",
                "name_it": "Terreno",
                "description_en": "Mountains, peaks, valleys, and other terrain features",
                "description_fr": "Montagnes, sommets, vallées et autres caractéristiques du terrain",
                "description_it": "Montagne, cime, valli e altre caratteristiche del terreno"
            },
            "order": 10
        },
        {
            "slug": "hydrographic",
            "name": "Gewässer",
            "description": "Seen, Flüsse, Wasserfälle, Gletscher und andere Gewässer",
            "i18n": {
                "name_en": "Water",
                "name_fr": "Eau",
                "name_it": "Acqua",
                "description_en": "Lakes, rivers, waterfalls, glaciers, and other water features",
                "description_fr": "Lacs, rivières, cascades, glaciers et autres plans d'eau",
                "description_it": "Laghi, fiumi, cascate, ghiacciai e altre caratteristiche idriche"
            },
            "order": 20
        },
        {
            "slug": "populated_place",
            "name": "Siedlung",
            "description": "Städte, Gemeinden, Dörfer und andere besiedelte Orte",
            "i18n": {
                "name_en": "Settlement",
                "name_fr": "Lieu habité",
                "name_it": "Insediamento",
                "description_en": "Cities, towns, villages, and other populated places",
                "description_fr": "Villes, communes, villages et autres lieux habités",
                "description_it": "Città, paesi, villaggi e altri luoghi abitati"
            },
            "order": 30
        },
        {
            "slug": "administrative",
            "name": "Verwaltung",
            "description": "Regionen und Verwaltungsgliederungen",
            "i18n": {
                "name_en": "Administrative",
                "name_fr": "Administratif",
                "name_it": "Amministrativo",
                "description_en": "Regions and administrative divisions",
                "description_fr": "Régions et divisions administratives",
                "description_it": "Regioni e divisioni amministrative"
            },
            "order": 40
        },
        {
            "slug": "transport",
            "name": "Verkehr",
            "description": "Bahnhöfe, Haltestellen, Parkplätze und Verkehrsinfrastruktur",
            "i18n": {
                "name_en": "Transport",
                "name_fr": "Transport",
                "name_it": "Trasporti",
                "description_en": "Stations, stops, parking, and transport infrastructure",
                "description_fr": "Gares, arrêts, parkings et infrastructures de transport",
                "description_it": "Stazioni, fermate, parcheggi e infrastrutture di trasporto"
            },
            "order": 50
        },
        {
            "slug": "accommodation",
            "name": "Unterkunft",
            "description": "Hotels, Restaurants und Unterkunftsmöglichkeiten",
            "i18n": {
                "name_en": "Accommodation",
                "name_fr": "Hébergement",
                "name_it": "Alloggio",
                "description_en": "Hotels, restaurants, and accommodation facilities",
                "description_fr": "Hôtels, restaurants et établissements d'hébergement",
                "description_it": "Hotel, ristoranti e strutture ricettive"
            },
            "order": 60
        },
        {
            "slug": "spot",
            "name": "Sehenswürdigkeit",
            "description": "Wahrzeichen, Attraktionen und Sehenswürdigkeiten",
            "i18n": {
                "name_en": "Point of Interest",
                "name_fr": "Point d'intérêt",
                "name_it": "Punto di interesse",
                "description_en": "Landmarks, attractions, and points of interest",
                "description_fr": "Monuments, attractions et points d'intérêt",
                "description_it": "Monumenti, attrazioni e punti di interesse"
            },
            "order": 70
        },
    ]

    # Child categories configuration: (parent_slug, child_slug, name_de, description_de, i18n_translations, order)
    child_categories = [
        # Terrain children
        ("terrain", "peak", "Gipfel", "Berggipfel oder Bergspitze", {"name_en": "Peak", "name_fr": "Sommet", "name_it": "Cima", "description_en": "Mountain peak or summit", "description_fr": "Sommet de montagne", "description_it": "Cima o vetta di montagna"}, 10),
        ("terrain", "pass", "Pass", "Bergpass oder Sattel", {"name_en": "Pass", "name_fr": "Col", "name_it": "Passo", "description_en": "Mountain pass or saddle", "description_fr": "Col de montagne", "description_it": "Passo di montagna"}, 20),
        ("terrain", "valley", "Tal", "Tal", {"name_en": "Valley", "name_fr": "Vallée", "name_it": "Valle", "description_en": "Valley", "description_fr": "Vallée", "description_it": "Valle"}, 30),
        ("terrain", "plateau", "Hochebene", "Hochebene oder Plateau", {"name_en": "Plateau", "name_fr": "Plateau", "name_it": "Altopiano", "description_en": "Plateau or elevated plain", "description_fr": "Plateau ou plaine élevée", "description_it": "Altopiano o pianura elevata"}, 40),
        ("terrain", "ridge", "Grat", "Berggrat", {"name_en": "Ridge", "name_fr": "Crête", "name_it": "Cresta", "description_en": "Mountain ridge", "description_fr": "Crête de montagne", "description_it": "Cresta montana"}, 50),
        ("terrain", "gorge", "Schlucht", "Schlucht oder Canyon", {"name_en": "Gorge", "name_fr": "Gorge", "name_it": "Gola", "description_en": "Gorge or canyon", "description_fr": "Gorge ou canyon", "description_it": "Gola o canyon"}, 60),
        ("terrain", "hill", "Hügel", "Hügel oder Anhöhe", {"name_en": "Hill", "name_fr": "Colline", "name_it": "Collina", "description_en": "Hill or small elevation", "description_fr": "Colline ou petite élévation", "description_it": "Collina o piccola elevazione"}, 70),
        ("terrain", "spur", "Ausläufer", "Bergausläufer", {"name_en": "Spur", "name_fr": "Contrefort", "name_it": "Sperone", "description_en": "Mountain spur", "description_fr": "Contrefort de montagne", "description_it": "Sperone montano"}, 80),
        ("terrain", "cape", "Kap", "Kap oder Landspitze", {"name_en": "Cape", "name_fr": "Cap", "name_it": "Capo", "description_en": "Cape or headland", "description_fr": "Cap ou promontoire", "description_it": "Capo o promontorio"}, 90),
        ("terrain", "island", "Insel", "Insel", {"name_en": "Island", "name_fr": "Île", "name_it": "Isola", "description_en": "Island", "description_fr": "Île", "description_it": "Isola"}, 100),

        # Hydrographic children
        ("hydrographic", "lake", "See", "See oder Weiher", {"name_en": "Lake", "name_fr": "Lac", "name_it": "Lago", "description_en": "Lake or pond", "description_fr": "Lac ou étang", "description_it": "Lago o stagno"}, 10),
        ("hydrographic", "waterfall", "Wasserfall", "Wasserfall oder Kaskade", {"name_en": "Waterfall", "name_fr": "Cascade", "name_it": "Cascata", "description_en": "Waterfall or cascade", "description_fr": "Cascade", "description_it": "Cascata"}, 20),
        ("hydrographic", "glacier", "Gletscher", "Gletscher oder Eisfeld", {"name_en": "Glacier", "name_fr": "Glacier", "name_it": "Ghiacciaio", "description_en": "Glacier or icefield", "description_fr": "Glacier ou champ de glace", "description_it": "Ghiacciaio o campo di ghiaccio"}, 30),
        ("hydrographic", "stream", "Bach", "Bach, Fluss oder Wasserlauf", {"name_en": "Stream", "name_fr": "Cours d'eau", "name_it": "Torrente", "description_en": "Stream, river, or creek", "description_fr": "Ruisseau, rivière ou cours d'eau", "description_it": "Torrente, fiume o ruscello"}, 40),
        ("hydrographic", "reservoir", "Stausee", "Stausee oder künstlicher See", {"name_en": "Reservoir", "name_fr": "Réservoir", "name_it": "Bacino", "description_en": "Reservoir or artificial lake", "description_fr": "Réservoir ou lac artificiel", "description_it": "Bacino o lago artificiale"}, 45),
        ("hydrographic", "bay", "Bucht", "Bucht oder Golf", {"name_en": "Bay", "name_fr": "Baie", "name_it": "Baia", "description_en": "Bay or gulf", "description_fr": "Baie ou golfe", "description_it": "Baia o golfo"}, 50),

        # Populated place children
        ("populated_place", "city", "Stadt", "Großstadt oder urbanes Gebiet", {"name_en": "City", "name_fr": "Ville", "name_it": "Città", "description_en": "Major city or urban area", "description_fr": "Grande ville ou zone urbaine", "description_it": "Grande città o area urbana"}, 10),
        ("populated_place", "town", "Kleinstadt", "Kleinstadt", {"name_en": "Town", "name_fr": "Ville", "name_it": "Paese", "description_en": "Town", "description_fr": "Ville", "description_it": "Paese"}, 20),
        ("populated_place", "village", "Dorf", "Dorf oder kleine Siedlung", {"name_en": "Village", "name_fr": "Village", "name_it": "Villaggio", "description_en": "Village or small settlement", "description_fr": "Village ou petit hameau", "description_it": "Villaggio o piccolo insediamento"}, 30),
        ("populated_place", "capital", "Hauptstadt", "Landes- oder Regionalhauptstadt", {"name_en": "Capital", "name_fr": "Capitale", "name_it": "Capitale", "description_en": "National or regional capital", "description_fr": "Capitale nationale ou régionale", "description_it": "Capitale nazionale o regionale"}, 40),

        # Administrative children
        ("administrative", "region", "Region", "Geografische oder administrative Region", {"name_en": "Region", "name_fr": "Région", "name_it": "Regione", "description_en": "Geographic or administrative region", "description_fr": "Région géographique ou administrative", "description_it": "Regione geografica o amministrativa"}, 10),

        # Transport children
        ("transport", "train_station", "Bahnhof", "Bahnhof oder Haltestelle", {"name_en": "Train Station", "name_fr": "Gare", "name_it": "Stazione ferroviaria", "description_en": "Railway station or stop", "description_fr": "Gare ou arrêt ferroviaire", "description_it": "Stazione o fermata ferroviaria"}, 10),
        ("transport", "bus_stop", "Bushaltestelle", "Busbahnhof oder Bushaltestelle", {"name_en": "Bus Stop", "name_fr": "Arrêt de bus", "name_it": "Fermata dell'autobus", "description_en": "Bus station or stop", "description_fr": "Gare routière ou arrêt de bus", "description_it": "Stazione o fermata dell'autobus"}, 20),
        ("transport", "metro_station", "U-Bahn-Station", "U-Bahn-Station", {"name_en": "Metro Station", "name_fr": "Station de métro", "name_it": "Stazione della metropolitana", "description_en": "Metro or subway station", "description_fr": "Station de métro", "description_it": "Stazione della metropolitana"}, 30),
        ("transport", "tram_stop", "Tramhaltestelle", "Tramhaltestelle", {"name_en": "Tram Stop", "name_fr": "Arrêt de tram", "name_it": "Fermata del tram", "description_en": "Tram stop", "description_fr": "Arrêt de tram", "description_it": "Fermata del tram"}, 40),
        ("transport", "airport", "Flughafen", "Flughafen", {"name_en": "Airport", "name_fr": "Aéroport", "name_it": "Aeroporto", "description_en": "Airport", "description_fr": "Aéroport", "description_it": "Aeroporto"}, 50),
        ("transport", "ferry", "Fähre", "Fähre oder Fährterminal", {"name_en": "Ferry", "name_fr": "Ferry", "name_it": "Traghetto", "description_en": "Ferry or ferry terminal", "description_fr": "Ferry ou terminal de ferry", "description_it": "Traghetto o terminal traghetti"}, 60),
        ("transport", "parking", "Parkplatz", "Parkplatz", {"name_en": "Parking", "name_fr": "Parking", "name_it": "Parcheggio", "description_en": "Parking area", "description_fr": "Zone de stationnement", "description_it": "Area di parcheggio"}, 70),

        # Accommodation children
        ("accommodation", "restaurant", "Restaurant", "Restaurant oder Gaststätte", {"name_en": "Restaurant", "name_fr": "Restaurant", "name_it": "Ristorante", "description_en": "Restaurant or dining facility", "description_fr": "Restaurant ou établissement de restauration", "description_it": "Ristorante o locale per ristorazione"}, 10),

        # Spot children
        ("spot", "church", "Kirche", "Kirche oder religiöses Gebäude", {"name_en": "Church", "name_fr": "Église", "name_it": "Chiesa", "description_en": "Church or religious building", "description_fr": "Église ou bâtiment religieux", "description_it": "Chiesa o edificio religioso"}, 10),
        ("spot", "castle", "Burg", "Burg oder Festung", {"name_en": "Castle", "name_fr": "Château", "name_it": "Castello", "description_en": "Castle or fortress", "description_fr": "Château ou forteresse", "description_it": "Castello o fortezza"}, 20),
        ("spot", "viewpoint", "Aussichtspunkt", "Aussichtspunkt oder Beobachtungsstelle", {"name_en": "Viewpoint", "name_fr": "Point de vue", "name_it": "Punto panoramico", "description_en": "Scenic viewpoint or observation point", "description_fr": "Point de vue panoramique", "description_it": "Punto panoramico"}, 30),
        ("spot", "cave", "Höhle", "Höhle", {"name_en": "Cave", "name_fr": "Grotte", "name_it": "Grotta", "description_en": "Cave", "description_fr": "Grotte", "description_it": "Grotta"}, 40),
        ("spot", "museum", "Museum", "Museum", {"name_en": "Museum", "name_fr": "Musée", "name_it": "Museo", "description_en": "Museum", "description_fr": "Musée", "description_it": "Museo"}, 50),
        ("spot", "recreation", "Freizeitanlage", "Freizeitanlage oder Erholungsgebiet", {"name_en": "Recreation", "name_fr": "Loisirs", "name_it": "Ricreazione", "description_en": "Recreation area or facility", "description_fr": "Zone de loisirs ou installation", "description_it": "Area o struttura ricreativa"}, 60),
        ("spot", "park", "Park", "Park oder Naturgebiet", {"name_en": "Park", "name_fr": "Parc", "name_it": "Parco", "description_en": "Park or nature area", "description_fr": "Parc ou zone naturelle", "description_it": "Parco o area naturale"}, 70),
        ("spot", "dam", "Staudamm", "Staudamm", {"name_en": "Dam", "name_fr": "Barrage", "name_it": "Diga", "description_en": "Dam", "description_fr": "Barrage", "description_it": "Diga"}, 80),
    ]

    # Feature to category mapping: feature_id -> (parent_slug, child_slug)
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
        "T.RDG": ("terrain", "ridge"),
        "T.RDGE": ("terrain", "ridge"),
        "T.GRGE": ("terrain", "gorge"),
        "T.CNYN": ("terrain", "gorge"),
        "T.HLL": ("terrain", "hill"),
        "T.HLLS": ("terrain", "hill"),
        "T.SPUR": ("terrain", "spur"),
        "T.CAPE": ("terrain", "cape"),
        "T.ISL": ("terrain", "island"),
        "T.ISLS": ("terrain", "island"),

        # Hydrographic features
        "H.LK": ("hydrographic", "lake"),
        "H.LKS": ("hydrographic", "lake"),
        "H.FLLS": ("hydrographic", "waterfall"),
        "H.GLCR": ("hydrographic", "glacier"),
        "H.STM": ("hydrographic", "stream"),
        "H.STMS": ("hydrographic", "stream"),
        "H.BAY": ("hydrographic", "bay"),
        "H.GULF": ("hydrographic", "bay"),

        # Populated places
        "P.PPL": ("populated_place", "village"),
        "P.PPLA": ("populated_place", "city"),
        "P.PPLA2": ("populated_place", "city"),
        "P.PPLA3": ("populated_place", "town"),
        "P.PPLA4": ("populated_place", "village"),
        "P.PPLC": ("populated_place", "capital"),

        # Administrative
        "L.RGN": ("administrative", "region"),

        # Transport
        "S.RSTN": ("transport", "train_station"),
        "S.RSTP": ("transport", "train_station"),
        "S.BUSTN": ("transport", "bus_stop"),
        "S.BUSTP": ("transport", "bus_stop"),
        "S.MTRO": ("transport", "metro_station"),
        "S.TRAM": ("transport", "tram_stop"),
        "S.AIRP": ("transport", "airport"),
        "S.FY": ("transport", "ferry"),
        "S.FYT": ("transport", "ferry"),
        "S.PKLT": ("transport", "parking"),

        # Accommodation
        "S.REST": ("accommodation", "restaurant"),

        # Spot/POI
        "S.CH": ("spot", "church"),
        "S.CSTL": ("spot", "castle"),
        "S.OBPT": ("spot", "viewpoint"),
        "S.CAVE": ("spot", "cave"),
        "S.MUS": ("spot", "museum"),
        "S.RECG": ("spot", "recreation"),
        "S.PRK": ("spot", "park"),
        "S.DAM": ("spot", "dam"),
    }

    print("Creating parent categories...")
    parent_map = {}
    for parent_data in parent_categories:
        # Check if parent already exists
        parent, created = Category.objects.get_or_create(
            slug=parent_data["slug"],
            parent=None,
            defaults={
                "name": parent_data["name"],
                "description": parent_data["description"],
                "order": parent_data["order"],
                "is_active": True,
            }
        )

        needs_update = False

        if created:
            # Set i18n translations for new categories
            parent.i18n = parent_data["i18n"]
            needs_update = True
            print(f"  Created parent: {parent.slug} ({parent.name})")
        else:
            print(f"  Skipped existing parent: {parent.slug} ({parent.name})")

        # Note: Symbols are handled by categories.0009_migrate_category_symbols
        # which runs before this migration (see dependency on categories.0010)

        if needs_update:
            parent.save()

        parent_map[parent_data["slug"]] = parent

    print("\nCreating child categories...")
    category_map = {}
    for parent_slug, child_slug, name_de, description_de, i18n_data, order in child_categories:
        parent = parent_map[parent_slug]

        # Check if child already exists
        child, created = Category.objects.get_or_create(
            slug=child_slug,
            parent=parent,
            defaults={
                "name": name_de,
                "description": description_de,
                "order": order,
                "is_active": True,
            }
        )

        needs_update = False

        if created:
            # Set i18n translations for new categories
            child.i18n = i18n_data
            needs_update = True
            print(f"  Created child: {parent_slug}.{child_slug} ({name_de})")
        else:
            print(f"  Skipped existing child: {parent_slug}.{child_slug} ({child.name})")

        # Note: Symbols are handled by categories.0009_migrate_category_symbols
        # which runs before this migration (see dependency on categories.0010)

        if needs_update:
            child.save()

        category_map[(parent_slug, child_slug)] = child

    print("\nMapping features to categories...")
    mapped_count = 0
    for feature_id, (parent_slug, child_slug) in feature_category_mapping.items():
        category = category_map.get((parent_slug, child_slug))
        if not category:
            print(f"  WARNING: Category not found for {parent_slug}.{child_slug}")
            continue

        updated = Feature.objects.filter(id=feature_id).update(category=category)
        if updated:
            mapped_count += 1
            print(f"  Mapped {feature_id} -> {parent_slug}.{child_slug}")
        else:
            print(f"  WARNING: Feature {feature_id} not found")

    print(f"\nCompleted: Created {len(parent_map)} parent categories, {len(category_map)} child categories, mapped {mapped_count} features")


def reverse_categories(apps, schema_editor):
    """Remove category mappings and delete created categories."""
    Category = apps.get_model("categories", "Category")
    Feature = apps.get_model("external_geonames", "Feature")

    # Clear feature mappings
    Feature.objects.filter(category__isnull=False).update(category=None)

    # Delete categories (cascade will handle children)
    # Use order_by() to clear the default ordering which references name_i18n
    parent_slugs = ["terrain", "hydrographic", "populated_place", "administrative", "transport", "spot"]
    Category.objects.filter(slug__in=parent_slugs, parent=None).order_by().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("geometries", "0001_initial"),
        ("categories", "0010_cleanup_symbol_fields"),  # Need symbol fields fully migrated and renamed
        ("external_geonames", "0007_feature_category"),
    ]

    operations = [
        migrations.RunPython(create_categories_and_map_features, reverse_code=reverse_categories),
    ]

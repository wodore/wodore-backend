"""Add French and Italian translations to hut type and availability categories.

The hut type categories were migrated from the legacy HutType model
(0002_migrate_huttype_data) whose fixture only ever defined name_en /
description_en. French and Italian users therefore fell back to the German
base name (e.g. 'einfaches Hotel' for lang=fr).

This migration merges name_fr / name_it (+ description_fr / description_it
where a description exists) into the modeltrans i18n dicts. It is
idempotent: existing keys are never overwritten.
"""

from django.db import migrations

# slug -> translations for children of 'accommodation' (hut types)
ACCOMMODATION_TRANSLATIONS = {
    "unknown": {
        "name_fr": "inconnu",
        "name_it": "sconosciuto",
        "description_fr": "type de cabane inconnu",
        "description_it": "tipo di capanna sconosciuto",
    },
    "closed": {
        "name_fr": "fermé",
        "name_it": "chiuso",
        "description_fr": "cabane fermée et non utilisable (pas d'abri d'urgence)",
        "description_it": "capanna chiusa e non utilizzabile (nessun riparo d'emergenza)",
    },
    "campgr": {
        "name_fr": "place de bivouac",
        "name_it": "posto di bivacco",
        "description_fr": "éventuel lieu de bivouac, sans infrastructure",
        "description_it": "possibile posto di bivacco, senza infrastruttura",
    },
    "shelter": {
        "name_fr": "abri simple",
        "name_it": "ricovero semplice",
        "description_fr": "abri simple sans grande infrastructure",
        "description_it": "ricovero semplice senza molta infrastruttura",
    },
    "camping": {
        "name_fr": "camping",
        "name_it": "campeggio",
        "description_fr": "camping avec infrastructure",
        "description_it": "campeggio con infrastruttura",
    },
    "bivouac": {
        "name_fr": "bivouac",
        "name_it": "bivacco",
        "description_fr": "bivouac, souvent en altitude avec un accès difficile",
        "description_it": "bivacco, spesso in alta quota con accesso difficile",
    },
    "selfhut": {
        "name_fr": "cabane non gardée",
        "name_it": "capanna non custodita",
        "description_fr": "cabane non gardée, souvent bien équipée",
        "description_it": "capanna non custodita, spesso ben attrezzata",
    },
    "hut": {
        "name_fr": "cabane",
        "name_it": "capanna",
        "description_fr": "cabane (de montagne) gardée, peut être non gardée hors saison",
        "description_it": "capanna (di montagna) custodita, può essere non custodita fuori stagione",
    },
    "alp": {
        "name_fr": "alpage",
        "name_it": "alpe",
        "description_fr": "alpage avec possibilité d'hébergement",
        "description_it": "alpe con possibilità di pernottamento",
    },
    "bhotel": {
        "name_fr": "hôtel simple",
        "name_it": "hotel semplice",
        "description_fr": "hôtel simple, non luxueux et abordable, souvent avec dortoir",
        "description_it": "hotel semplice, non di lusso ed economico, spesso con camerata",
    },
    "hostel": {
        "name_fr": "auberge de jeunesse",
        "name_it": "ostello",
    },
    "special": {
        "name_fr": "spécial",
        "name_it": "speciale",
        "description_fr": "forme d'hébergement particulière",
        "description_it": "soluzione di pernottamento particolare",
    },
    "hotel": {
        "name_fr": "hôtel",
        "name_it": "hotel",
    },
    "resta": {
        "name_fr": "restaurant",
        "name_it": "ristorante",
        "description_fr": "restaurant sans possibilité d'hébergement",
        "description_it": "ristorante senza possibilità di pernottamento",
    },
}

# slug -> translations for children of 'availability'
AVAILABILITY_TRANSLATIONS = {
    "unknown": {"name_fr": "Inconnu", "name_it": "Sconosciuto"},
    "empty": {"name_fr": "Libre", "name_it": "Libero"},
    "low": {"name_fr": "Bas", "name_it": "Basso"},
    "medium": {"name_fr": "Moyen", "name_it": "Medio"},
    "high": {"name_fr": "Élevé", "name_it": "Alto"},
    "full": {"name_fr": "Complet", "name_it": "Pieno"},
}


def add_translations(apps, schema_editor):
    Category = apps.get_model("categories", "Category")

    plan = {
        "accommodation": ACCOMMODATION_TRANSLATIONS,
        "availability": AVAILABILITY_TRANSLATIONS,
    }

    updated = 0
    for parent_slug, translations in plan.items():
        for cat in Category.objects.filter(parent__slug=parent_slug):
            additions = translations.get(cat.slug)
            if not additions:
                print(f"  ⊘ no translation plan for {parent_slug}/{cat.slug}")
                continue
            i18n = dict(cat.i18n) if isinstance(cat.i18n, dict) else {}
            changed = False
            for key, value in additions.items():
                if not i18n.get(key):
                    i18n[key] = value
                    changed = True
            if changed:
                cat.i18n = i18n
                cat.save(update_fields=["i18n"])
                updated += 1

    print(f"✓ Added fr/it translations to {updated} categories")


def remove_translations(apps, schema_editor):
    """Reverse: drop the fr/it keys added above."""
    Category = apps.get_model("categories", "Category")
    plan = {
        "accommodation": ACCOMMODATION_TRANSLATIONS,
        "availability": AVAILABILITY_TRANSLATIONS,
    }
    removed = 0
    for parent_slug, translations in plan.items():
        for cat in Category.objects.filter(parent__slug=parent_slug):
            additions = translations.get(cat.slug)
            if not additions or not isinstance(cat.i18n, dict):
                continue
            i18n = {k: v for k, v in cat.i18n.items() if k not in additions}
            if len(i18n) != len(cat.i18n):
                cat.i18n = i18n
                cat.save(update_fields=["i18n"])
                removed += 1
    print(f"✓ Removed fr/it translations from {removed} categories")


class Migration(migrations.Migration):
    dependencies = [
        ("categories", "0015_category_categories__parent__91c7d9_idx"),
    ]

    operations = [
        migrations.RunPython(add_translations, remove_translations),
    ]

from django.db import migrations

# Accommodation glyph palette (round 6, design session 261012):
# one semantic color per type, shape-first / colorblind-aware.
# hut burnt-orange · selfhut dark brown · bivouac violet · shelter amber
# campgr olive · camping green · alp brown (cow) · bhotel steel
# hostel royal blue · hotel violet · resta red · special pink
# closed/unknown achromatic state colors.
ACCOMMODATION_COLORS = {
    "hut": "#C05621",
    "selfhut": "#5D4433",
    "bivouac": "#6B46C1",
    "shelter": "#CA8A04",
    "campgr": "#6B8F3D",
    "camping": "#2F855A",
    "alp": "#8F5F35",
    "bhotel": "#47617E",
    "hostel": "#2563EB",
    "hotel": "#8B5CF6",
    "special": "#D53F8C",
    "resta": "#E53E3E",
    "closed": "#718096",
    "unknown": "#A0AEC0",
}


def set_colors(apps, schema_editor):
    Category = apps.get_model("categories", "Category")
    parent = Category.objects.filter(parent=None, slug="accommodation").first()
    if not parent:
        return
    for slug, color in ACCOMMODATION_COLORS.items():
        Category.objects.filter(parent=parent, slug=slug).update(color=color)


def unset_colors(apps, schema_editor):
    # Previous values were not homogeneous (several types shared #4B8E43);
    # restore that shared default as a best-effort reverse.
    Category = apps.get_model("categories", "Category")
    parent = Category.objects.filter(parent=None, slug="accommodation").first()
    if not parent:
        return
    Category.objects.filter(parent=parent, slug__in=ACCOMMODATION_COLORS).update(
        color="#4B8E43"
    )


class Migration(migrations.Migration):
    dependencies = [
        ("categories", "0017_category_seo_sitemap"),
    ]

    operations = [
        migrations.RunPython(set_colors, unset_colors),
    ]

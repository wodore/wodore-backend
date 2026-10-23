# Generated manually — strips the ``.pbf`` suffix from Martin glyph
# templates stored in already-seeded ``MapLayer.style`` documents.
#
# Martin (<= 1.16.1, the pinned prod/stage image) answers
# ``/font/{stack}/{range}.pbf`` with a 301 to the canonical
# extension-less route while DROPPING the query string
# (``redirect_font_ext`` — unlike the tile redirect, which preserves
# it). With the serve-time ``?v=`` asset version appended, every glyph
# request therefore paid an extra redirect round-trip and landed on an
# unversioned URL whose cache key never rotates on font changes. The
# canonical route answers 200 directly with the query intact.
#
# Surgical on purpose: only the exact authored template suffix is
# rewritten, so curated styles (external glyph URLs, hand-edited
# documents) are untouched. A fresh ``map_seed`` plants the same
# extension-less templates (fixtures + seed_lib changed in step).

from django.db import migrations

SUFFIX = "/font/{fontstack}/{range}.pbf"
CANONICAL = "/font/{fontstack}/{range}"


def strip_pbf(apps, schema_editor):
    MapLayer = apps.get_model("basemaps", "MapLayer")
    for layer in MapLayer.objects.filter(style__isnull=False):
        style = layer.style
        if not isinstance(style, dict):
            continue
        glyphs = style.get("glyphs")
        if isinstance(glyphs, str) and glyphs.endswith(SUFFIX):
            style["glyphs"] = glyphs[: -len(".pbf")]
            layer.save(update_fields=["style"])


def restore_pbf(apps, schema_editor):
    MapLayer = apps.get_model("basemaps", "MapLayer")
    for layer in MapLayer.objects.filter(style__isnull=False):
        style = layer.style
        if not isinstance(style, dict):
            continue
        glyphs = style.get("glyphs")
        if isinstance(glyphs, str) and glyphs.endswith(CANONICAL):
            style["glyphs"] = glyphs + ".pbf"
            layer.save(update_fields=["style"])


class Migration(migrations.Migration):
    dependencies = [
        ("basemaps", "0009_ogmap_maintenance"),
    ]

    operations = [
        migrations.RunPython(strip_pbf, restore_pbf),
    ]

"""Rewrite legacy {TILE_SERVER_URL} placeholders to the env token.

Authored styles reference the tile origin through the standard
``{{env:MARTIN_TILE_URL}}`` registry token; the legacy single-brace
placeholder keeps working (resolution alias), but stored rows are
migrated to the canonical form. Depends on the envvars URL-origin seed
so the registry row exists before any style references the token
(env-gated layers are hidden while a name is unresolvable).
"""

from django.db import migrations

LEGACY = "{TILE_SERVER_URL}"
TOKEN = "{{env:MARTIN_TILE_URL}}"


def _rewrite(value):
    if isinstance(value, str):
        return value.replace(LEGACY, TOKEN)
    if isinstance(value, dict):
        return {key: _rewrite(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_rewrite(child) for child in value]
    return value


def _rewrite_back(value):
    if isinstance(value, str):
        return value.replace(TOKEN, LEGACY)
    if isinstance(value, dict):
        return {key: _rewrite_back(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_rewrite_back(child) for child in value]
    return value


def forwards(apps, schema_editor):
    MapLayer = apps.get_model("basemaps", "MapLayer")
    for layer in MapLayer.objects.iterator():
        changed = False
        if isinstance(layer.style, dict):
            style = _rewrite(layer.style)
            if style != layer.style:
                layer.style = style
                changed = True
        if layer.style_url and LEGACY in layer.style_url:
            layer.style_url = layer.style_url.replace(LEGACY, TOKEN)
            changed = True
        if changed:
            # ``modified`` re-keys the style body cache (version-keyed).
            layer.save(update_fields=["style", "style_url", "modified"])


def backwards(apps, schema_editor):
    MapLayer = apps.get_model("basemaps", "MapLayer")
    for layer in MapLayer.objects.iterator():
        changed = False
        if isinstance(layer.style, dict):
            style = _rewrite_back(layer.style)
            if style != layer.style:
                layer.style = style
                changed = True
        if layer.style_url and TOKEN in layer.style_url:
            layer.style_url = layer.style_url.replace(TOKEN, LEGACY)
            changed = True
        if changed:
            layer.save(update_fields=["style", "style_url", "modified"])


class Migration(migrations.Migration):
    dependencies = [
        ("basemaps", "0010_strip_pbf_from_martin_glyph_templates"),
        ("envvars", "0004_seed_url_origins"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]

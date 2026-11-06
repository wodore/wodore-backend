from django.db import migrations

# Symbol style variants renamed (design session 261012):
#   detailed → color, simple → primitive (mono unchanged)
# Accompanies the field renames on Category/Icon (symbol_color/symbol_primitive)
# and the sprite variant dirs (color/primitive/mono). Data first so the new
# style CHECK constraint (added in the follow-up migration) validates.
STYLE_RENAMES = {
    "detailed": "color",
    "simple": "primitive",
    "detailed-animated": "color-animated",
    # legacy value that predates the current choices; outlined-mono ≈ mono
    "outlined-mono": "mono",
    "simple-animated": "primitive-animated",
}


def forwards(apps, schema_editor):
    Symbol = apps.get_model("symbols", "Symbol")
    for old, new in STYLE_RENAMES.items():
        Symbol.objects.filter(style=old).update(style=new)


def backwards(apps, schema_editor):
    Symbol = apps.get_model("symbols", "Symbol")
    for old, new in STYLE_RENAMES.items():
        Symbol.objects.filter(style=new).update(style=old)


class Migration(migrations.Migration):
    dependencies = [
        ("symbols", "0011_iconkeyword_folded_trgm_index"),
    ]

    operations = [
        # Old CHECK only allows the legacy values — drop (state-aware)
        # before renaming them. 0013 re-adds it with the new value list.
        migrations.RemoveConstraint(
            model_name="symbol",
            name="symbols_symbol_style_valid",
        ),
        migrations.RunPython(forwards, backwards),
    ]

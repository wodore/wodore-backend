# Generated manually — moves every existing symbol SVG onto its
# content-hashed canonical name (see server/apps/symbols/storage.py).
#
# Media is served immutable+30d, and the deterministic names used so far
# could change content (icon-import re-writes), leaving browsers on stale
# bytes for the cache lifetime. After this migration a URL maps to exactly
# one content version forever; re-uploads of identical content deduplicate.
#
# Reverse is a documented no-op: content is unchanged, and regenerating
# the old (unsafe) names has no value.

from django.db import migrations

from server.apps.symbols.storage import canonicalize_symbol_storage


def canonicalize(apps, schema_editor):
    Symbol = apps.get_model("symbols", "Symbol")
    canonicalize_symbol_storage(Symbol)


class Migration(migrations.Migration):
    dependencies = [
        ("symbols", "0015_alter_symbol_svg_file"),
    ]

    operations = [
        migrations.RunPython(canonicalize, migrations.RunPython.noop),
    ]

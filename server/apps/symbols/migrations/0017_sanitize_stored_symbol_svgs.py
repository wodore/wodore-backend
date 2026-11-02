# Generated manually — sanitizes the stored bytes of every symbol SVG
# (see server.apps.symbols.storage.sanitize_symbol_storage).
#
# The color-variant files were written with lxml artifacts (``ns0:``
# element prefixes) or without a root ``xmlns`` declaration. Lenient
# consumers render them (HTML-inline parsing), but strict ones do not:
# browsers refuse to decode such an SVG inside an <img> (naturalWidth 0
# — every hut-detail type icon rendered as the broken-image placeholder)
# and Martin's sprite parser rejects them (NoRootNode). The
# sanitize-on-write hops landed with #477; this migration heals the
# files that predate them.
#
# Reverse is a documented no-op: re-introducing malformed bytes (the
# state this migration repairs) has no value.

from typing import Any

from django.db import migrations

from server.apps.symbols.storage import sanitize_symbol_storage


def sanitize(apps: Any, schema_editor: Any) -> None:
    Symbol = apps.get_model("symbols", "Symbol")
    sanitize_symbol_storage(Symbol)


class Migration(migrations.Migration):
    dependencies = [
        ("symbols", "0016_content_hash_symbol_files"),
    ]

    operations = [
        migrations.RunPython(sanitize, migrations.RunPython.noop),
    ]

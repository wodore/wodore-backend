"""Per-language prefix-search btrees (geoplace-read-performance).

The translated autocomplete arm of the place search pre-filters
through ``LOWER(i18n ->> 'name_xx') LIKE 'q%'`` — same pattern as the
base-name index (0070), extended to the three translations (the base
``name`` column IS the German name). ``text_pattern_ops`` for the
non-C collation (see 0070), partial on the search base filter, built
CONCURRENTLY.
"""

from django.db import migrations

LANGS = ("en", "fr", "it")


def _index_sql(lang: str) -> str:
    return (
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
        f"geoplaces_i18n_name_{lang}_lower_prefix_idx "
        "ON geometries_geoplace "
        f"USING btree (lower(i18n->>'name_{lang}') text_pattern_ops) "
        "WHERE is_public = true AND is_active = true"
    )


def _drop_sql(lang: str) -> str:
    return (
        "DROP INDEX CONCURRENTLY IF EXISTS "
        f"geoplaces_i18n_name_{lang}_lower_prefix_idx"
    )


class Migration(migrations.Migration):
    # CREATE INDEX CONCURRENTLY cannot run inside a transaction
    atomic = False

    dependencies = [
        ("geometries", "0070_name_prefix_index"),
    ]

    operations = [
        migrations.RunSQL(sql=_index_sql(lang), reverse_sql=_drop_sql(lang))
        for lang in LANGS
    ]

"""Prefix-search btree on lower(name) (geoplace-read-performance).

The autocomplete path of the place search pre-filters through
``LOWER(name) LIKE 'q%'`` — a btree range scan, the cheapest arm at
any table size and the only viable one for 1–2 character queries
(trigram similarity is noise that short, and the gin_trgm_ops GINs
cannot extract trigrams from single characters at all).

Partial (``is_public AND is_active``) to match the search base filter
exactly; built CONCURRENTLY — non-atomic migration, same pattern as
0069. ``text_pattern_ops`` is required: under the database's non-C
collation a plain btree on ``lower(name)`` cannot serve ``LIKE 'q%'``
prefix ranges (the planner falls back to sequence scans — the same
reason Django's auto-indexes carry ``varchar_pattern_ops`` ``_like``
twins). Measured: 0.1 ms index scan vs 21 ms seq scan at 440k rows.
"""

from django.db import migrations

INDEX_SQL = """
    CREATE INDEX CONCURRENTLY IF NOT EXISTS geoplaces_name_lower_prefix_idx
    ON geometries_geoplace
    USING btree (lower(name) text_pattern_ops)
    WHERE is_public = true AND is_active = true
"""

INDEX_REVERSE_SQL = "DROP INDEX CONCURRENTLY IF EXISTS geoplaces_name_lower_prefix_idx"


class Migration(migrations.Migration):
    # CREATE INDEX CONCURRENTLY cannot run inside a transaction
    atomic = False

    dependencies = [
        ("geometries", "0069_read_performance_indexes"),
    ]

    operations = [
        migrations.RunSQL(
            sql=INDEX_SQL,
            reverse_sql=INDEX_REVERSE_SQL,
        ),
    ]

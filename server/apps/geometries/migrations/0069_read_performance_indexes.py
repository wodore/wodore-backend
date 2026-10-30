"""Read-performance indexes + trigram threshold (geoplace-read-performance).

Measured at 440k places (work doc, 261029 follow-up):

* **nearby/radius** queries compile ``distance_lte=(point, D(m=…))`` to
  the *geography* ``ST_DWithin`` — the existing GIST indexes are
  *geometry*, so the planner fell back to scanning the
  ``(is_active, is_public, importance)`` index and computing the
  distance per row (~1.26 s). A partial **geography** GIST index serves
  it (~9 ms measured shape). Built CONCURRENTLY — non-atomic migration.
* **search** pre-filters candidates through ILIKE containment and the
  ``%`` similarity operator (both served by the per-language
  ``gin_trgm_ops`` GINs). ``%`` compares against
  ``pg_trgm.similarity_threshold`` (default 0.3); the API's threshold
  defaults to 0.2 and documents 0.1 — the DB-wide GUC floor of 0.1
  keeps ``%`` a loose superset for every supported threshold.
* the ``kind_slug`` rename carried the old ``detail_type`` auto index
  pair along (``db_index=True``) next to the Meta index — the model
  drops ``db_index`` and this migration removes the duplicates
  (hand-written: the autodetector names differ).
"""

from typing import Any

from django.db import migrations, models

GEOGRAPHY_INDEX_SQL = """
    CREATE INDEX CONCURRENTLY IF NOT EXISTS geoplaces_location_geography_gist_idx
    ON geometries_geoplace
    USING gist (geography(location))
    WHERE is_public = true AND is_active = true
"""

GEOGRAPHY_INDEX_REVERSE_SQL = (
    "DROP INDEX CONCURRENTLY IF EXISTS geoplaces_location_geography_gist_idx"
)


def set_trigram_threshold(_apps: Any, _schema_editor: Any) -> None:
    from psycopg import sql

    from django.db import connection

    db_name = connection.settings_dict["NAME"]
    with _schema_editor.connection.cursor() as cursor:
        stmt = sql.SQL(
            "ALTER DATABASE {} SET pg_trgm.similarity_threshold = %s"
        ).format(sql.Identifier(db_name))
        cursor.execute(stmt, ["0.1"])


class Migration(migrations.Migration):
    # CREATE INDEX CONCURRENTLY cannot run inside a transaction
    atomic = False

    dependencies = [
        ("geometries", "0068_tile_function_kind_slug"),
    ]

    operations = [
        migrations.RunSQL(
            sql=GEOGRAPHY_INDEX_SQL,
            reverse_sql=GEOGRAPHY_INDEX_REVERSE_SQL,
        ),
        # New connections only — pooled/existing sessions keep their
        # GUC until recycled; harmless (the prefilter just stays
        # stricter for them).
        migrations.RunPython(
            code=set_trigram_threshold,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="geoplace",
            name="kind_slug",
            field=models.CharField(
                default="none",
                help_text="Super-root identifier of the place's kind (derived)",
                max_length=100,
                verbose_name="Kind Slug",
            ),
        ),
        migrations.RunSQL(
            sql="DROP INDEX CONCURRENTLY IF EXISTS geometries_geoplace_detail_type_c038fb78",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql="DROP INDEX CONCURRENTLY IF EXISTS geometries_geoplace_detail_type_c038fb78_like",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("geometries", "0005_add_geoplace_i18n_trgm_indexes"),
    ]

    operations = [
        migrations.RunSQL(
            sql=(
                "CREATE INDEX IF NOT EXISTS "
                "geometries_geoplace_i18n_name_en_tsvector_idx "
                "ON geometries_geoplace "
                "USING GIN (to_tsvector('simple', i18n->>'name_en'));"
            ),
            reverse_sql=(
                "DROP INDEX IF EXISTS geometries_geoplace_i18n_name_en_tsvector_idx;"
            ),
        ),
        migrations.RunSQL(
            sql=(
                "CREATE INDEX IF NOT EXISTS "
                "geometries_geoplace_i18n_name_fr_tsvector_idx "
                "ON geometries_geoplace "
                "USING GIN (to_tsvector('simple', i18n->>'name_fr'));"
            ),
            reverse_sql=(
                "DROP INDEX IF EXISTS geometries_geoplace_i18n_name_fr_tsvector_idx;"
            ),
        ),
        migrations.RunSQL(
            sql=(
                "CREATE INDEX IF NOT EXISTS "
                "geometries_geoplace_i18n_name_it_tsvector_idx "
                "ON geometries_geoplace "
                "USING GIN (to_tsvector('simple', i18n->>'name_it'));"
            ),
            reverse_sql=(
                "DROP INDEX IF EXISTS geometries_geoplace_i18n_name_it_tsvector_idx;"
            ),
        ),
    ]

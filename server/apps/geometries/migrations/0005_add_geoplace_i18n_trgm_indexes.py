from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("geometries", "0004_alter_geoplacesourceassociation_source_id"),
    ]

    operations = [
        migrations.RunSQL(
            sql=(
                "CREATE INDEX IF NOT EXISTS "
                "geometries_geoplace_i18n_name_en_trgm_idx "
                "ON geometries_geoplace "
                "USING GIN ((i18n->>'name_en') gin_trgm_ops);"
            ),
            reverse_sql=(
                "DROP INDEX IF EXISTS geometries_geoplace_i18n_name_en_trgm_idx;"
            ),
        ),
        migrations.RunSQL(
            sql=(
                "CREATE INDEX IF NOT EXISTS "
                "geometries_geoplace_i18n_name_fr_trgm_idx "
                "ON geometries_geoplace "
                "USING GIN ((i18n->>'name_fr') gin_trgm_ops);"
            ),
            reverse_sql=(
                "DROP INDEX IF EXISTS geometries_geoplace_i18n_name_fr_trgm_idx;"
            ),
        ),
        migrations.RunSQL(
            sql=(
                "CREATE INDEX IF NOT EXISTS "
                "geometries_geoplace_i18n_name_it_trgm_idx "
                "ON geometries_geoplace "
                "USING GIN ((i18n->>'name_it') gin_trgm_ops);"
            ),
            reverse_sql=(
                "DROP INDEX IF EXISTS geometries_geoplace_i18n_name_it_trgm_idx;"
            ),
        ),
    ]

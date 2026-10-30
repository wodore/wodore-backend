"""GeoPlace.kind FK — the anchoring main category (geoplace-kind-fk).

The kind becomes a stored, indexed fact: ``kind = first category
association by ``(order, slug)`` — the exact rule every consumer
derived from so far (task 1.1/1.2). The association table stays the
source of truth for classifiers/extras (D1); the FK is the
denormalized anchor, re-derived on every write path alongside
``domain``.

The ``AlterField`` on ``domain`` rides along: it captures the
verbose_name/help_text corrections from the admin-label fix (no DB
change).

Backfill: one chunked-friendly UPDATE with a lateral subquery — the
per-row trigger overhead needs the lifted statement timeout (see
0066/0072).
"""

from typing import Any

import django.db.models.deletion
from django.db import migrations, models

BACKFILL_SQL = """
    UPDATE geometries_geoplace gp
    SET kind_id = (
        SELECT gpc.category_id
        FROM geometries_geoplace_category gpc
        JOIN categories_category cat ON gpc.category_id = cat.id
        WHERE gpc.geo_place_id = gp.id
        ORDER BY cat."order", cat.slug
        LIMIT 1
    )
    WHERE gp.kind_id IS NULL
"""


def backfill_kind(_apps: Any, schema_editor: Any) -> None:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SET LOCAL statement_timeout = '120s'")
        cursor.execute(BACKFILL_SQL)


def null_kind(_apps: Any, schema_editor: Any) -> None:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("UPDATE geometries_geoplace SET kind_id = NULL")


class Migration(migrations.Migration):

    dependencies = [
        ('categories', '0023_category_is_protected'),
        ('geometries', '0072_kind_slug_to_domain'),
    ]

    operations = [
        migrations.AddField(
            model_name='geoplace',
            name='kind',
            field=models.ForeignKey(blank=True, help_text='The anchoring main category (derived: first association by order, slug) — categories inline edits re-anchor on save', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='places_anchored', to='categories.category', verbose_name='Kind'),
        ),
        migrations.AlterField(
            model_name='geoplace',
            name='domain',
            field=models.CharField(default='none', help_text='Super-root tier of the place (derived) — amenity / admin / natural / none', max_length=100, verbose_name='Domain'),
        ),
        migrations.RunPython(backfill_kind, null_kind),
    ]
